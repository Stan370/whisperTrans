import sys
import os
from pathlib import Path

# Add the root directory to Python path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

import time
import whisper
import torch
import json
from typing import Dict, List, Optional
import google.generativeai as genai
from utils.config import settings, LANGUAGE_MAP
from core.models import TranslationTask, TaskStatus
from utils.logger import get_logger
from infrastructure.redis_client import redis_client

logger = get_logger("translation_service")

class TranslationService:
    """Centralized translation service for STT and translation processing."""
    
    def __init__(self):
        self.whisper_model = None
        self.gemini_model = None
        self._setup_models()
        
    def _get_device(self) -> str:
        """Get the best available device for Whisper."""
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        elif torch.cuda.is_available():
            return "cuda"
        else:
            return "cpu"

    def _setup_models(self):
        """Setup Whisper and translation models."""
        try:
            #
            if torch.cuda.is_available():
                device="cuda"
            device="cpu"
            self.whisper_model = whisper.load_model(settings.whisper_model, device=device)
            logger.info(f"Whisper model loaded: {settings.whisper_model}")
            # Setup Google Generative AI
            genai.configure(api_key=settings.google_api_key)
            self.gemini_model = genai.GenerativeModel('gemini-pro')
            logger.info("Google Generative AI configured")
            
        except Exception as e:
            logger.error(f"Failed to setup models: {e}")
            raise
    
    def calculate_wer(self, reference: str, hypothesis: str) -> float:
        """Calculate Word Error Rate between reference and hypothesis text."""
        ref_words = reference.split()
        hyp_words = hypothesis.split()
        
        if not ref_words:
            return 0.0
        
        # Create distance matrix
        d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
        for i in range(len(ref_words) + 1):
            d[i][0] = i
        for j in range(len(hyp_words) + 1):
            d[0][j] = j
        
        # Fill distance matrix
        for i in range(1, len(ref_words) + 1):
            for j in range(1, len(hyp_words) + 1):
                if ref_words[i-1] == hyp_words[j-1]:
                    d[i][j] = d[i-1][j-1]
                else:
                    d[i][j] = min(d[i-1][j], d[i][j-1], d[i-1][j-1]) + 1
                    
        return d[len(ref_words)][len(hyp_words)] / len(ref_words)
    
    def transcribe_audio(self, audio_file: str) -> dict:
        """Transcribe audio file using Whisper model."""
        try:
            start_time = time.time()
            logger.info(f"Calling Whisper STT on {audio_file}")
            
            # Standard Whisper returns a dictionary with 'text' and 'segments' keys
            result = self.whisper_model.transcribe(audio_file, fp16=False)

            # The raw transcription output will be saved later in a consolidated file.
            
            processing_time = time.time() - start_time
            logger.info(f"Transcribed {audio_file} in {processing_time:.2f}s")
            return result
        except Exception as e:
            logger.error(f"Failed to transcribe {audio_file}: {e}")
            raise
    
    def validate_stt_text(self, stt_text: str, reference_text: str) -> str:
        """Validate STT text against reference text using WER."""
        if not reference_text:
            return stt_text
        
        wer = self.calculate_wer(reference_text, stt_text)
        logger.info(f"WER for validation: {wer:.3f}")
        
        # If WER is too high, use reference text
        if wer > settings.wer_threshold:
            logger.warning(f"High WER ({wer:.3f}), using reference text")
            return reference_text
        
        return stt_text
    
    def translate_text(self, text: str, source_lang: str, target_lang: str) -> str:
        """Translate text using Gemini 2.0 Flash."""
        try:
            source_language_name = LANGUAGE_MAP.get(source_lang, source_lang)
            target_language_name = LANGUAGE_MAP.get(target_lang, target_lang)
            
            prompt = f"Translate the following text from {source_language_name} to {target_language_name}. Only return the translation, nothing else:\n\n{text}"
            
            response = self.gemini_model.generate_content(prompt)
            translated_text = response.text.strip()
            
            logger.info(f"Translated text to {target_lang}")
            return translated_text
            
        except Exception as e:
            logger.error(f"Translation failed for {target_lang}: {e}")
            return f"[Translation error: {str(e)}]"
    
    def process_audio_file(self, audio_file: str, file_id: str, 
                          reference_text: str, source_lang: str, 
                          target_languages: List[str]) -> dict:
        """Process a single audio file through STT and translation."""
        start_time = time.time()
        logger.info(f"Transcribing using whisper {audio_file}")
        try:
            # Step 1: Transcribe audio
            transcription_result = self.transcribe_audio(audio_file)
            stt_text = transcription_result.get("text", "").strip()
            
            # Step 2: Validate STT text
            validated_text = self.validate_stt_text(stt_text, reference_text)
            
            # Step 3: Calculate WER
            wer = self.calculate_wer(reference_text, stt_text) if reference_text else 0.0
            
            # Step 4: Translate to target languages
            translations = {}
            for target_lang in target_languages:
                translated_text = self.translate_text(validated_text, source_lang, target_lang)
                translations[target_lang] = translated_text
            
            processing_time = time.time() - start_time
            
            # Create result dictionary
            result = {
                "file_id": file_id,
                "original_text": reference_text,
                "stt_result": transcription_result,
                "wer": wer,
                "validated_text": validated_text,
                "translations": translations,
                "processing_time": processing_time
            }
            
            logger.info(f"Processed {file_id} in {processing_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Failed to process {file_id}: {e}")
            raise
    
    def process_task(self, task: TranslationTask) -> Dict:
        """Process a complete translation task."""
        packed_data = {}
        
        try:
            logger.info(f"Starting to process task {task.task_id}")
            
            # Initialize language structure
            if task.source_language not in packed_data:
                packed_data[task.source_language] = {}

            # Process each audio file
            for i, audio_file in enumerate(task.audio_files):
                file_id = os.path.splitext(os.path.basename(audio_file))[0]
                reference_text = task.text_data.get(file_id, "")
                
                # Process the audio file
                result = self.process_audio_file(
                    audio_file=audio_file,
                    file_id=file_id,
                    reference_text=reference_text,
                    source_lang=task.source_language,
                    target_languages=task.target_languages
                )
                
                # Structure the data as requested
                if file_id not in packed_data[task.source_language]:
                    packed_data[task.source_language][file_id] = {}
                
                packed_data[task.source_language][file_id]["TEXT"] = reference_text
                packed_data[task.source_language][file_id]["AUDIO"] = result["stt_result"]
                
                # Add translations to the structure
                for lang, text in result["translations"].items():
                    if lang not in packed_data:
                        packed_data[lang] = {}
                    if file_id not in packed_data[lang]:
                        packed_data[lang][file_id] = {}
                    packed_data[lang][file_id]["TRANSLATION"] = text

                logger.info(f"Completed {i+1}/{len(task.audio_files)} files for task {task.task_id}")

            self.store_results(task.task_id, packed_data)

            logger.info(f"Successfully processed task {task.task_id}")
            return packed_data
            
        except Exception as e:
            logger.error(f"Failed to process task {task.task_id}: {e}")
            raise
    
    def store_results(self, task_id: str, results: Dict) -> bool:
        """Store translation results."""
        try:
            # Store in Redis
            results_key = f"results:{task_id}"
            redis_client.set(results_key, json.dumps(results))
            
            # Also save to file system
            self._save_results_to_file(task_id, results)
            
            logger.info(f"Stored results for task {task_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to store results for task {task_id}: {e}")
            return False
    
    def _save_results_to_file(self, task_id: str, results: Dict):
        """Save results to JSON file in result directory."""
        try:
            from datetime import datetime, UTC
            
            # Create result directory if it doesn't exist
            result_dir = settings.result_dir
            os.makedirs(result_dir, exist_ok=True)
            
            # Create filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"task_{task_id}_{timestamp}.json"
            file_path = os.path.join(result_dir, filename)
            
            # Prepare data for JSON export
            export_data = {
                "task_id": task_id,
                "exported_at": datetime.now(UTC).isoformat(),
                "data": results
            }
            
            # Write to file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved results to file: {file_path}")
            
        except Exception as e:
            logger.error(f"Failed to save results to file for task {task_id}: {e}")
    
    def get_results_from_file(self, task_id: str) -> Optional[Dict]:
        """Get results from file system as backup to Redis."""
        try:
            import glob
            
            result_dir = settings.result_dir
            pattern = os.path.join(result_dir, f"task_{task_id}_*.json")
            files = glob.glob(pattern)
            
            if not files:
                return None
            latest_file = max(files, key=os.path.getctime)
            with open(latest_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logger.info(f"Loaded results from file: {latest_file}")
            return data.get("data")
            
        except Exception as e:
            logger.error(f"Failed to get results from file for task {task_id}: {e}")
            return None
    
    def get_result_filepath(self, task_id: str) -> Optional[str]:
        """Get the filepath of the result file for a specific task."""
        try:
            import glob
            
            result_dir = settings.result_dir
            pattern = os.path.join(result_dir, f"task_{task_id}_*.json")
            files = glob.glob(pattern)
            
            if not files:
                logger.warning(f"No result file found for task {task_id}")
                return None
            
            latest_file = max(files, key=os.path.getctime)
            return latest_file
            
        except Exception as e:
            logger.error(f"Failed to get result file path for task {task_id}: {e}")
            return None
    
    def list_result_files(self) -> List[Dict[str, str]]:
        """List all result files with metadata."""
        try:
            import glob
            from datetime import datetime
            
            result_dir = settings.result_dir
            if not os.path.exists(result_dir):
                return []
            
            pattern = os.path.join(result_dir, "task_*.json")
            files = glob.glob(pattern)
            
            result_files = []
            for file_path in files:
                try:
                    filename = os.path.basename(file_path)
                    file_size = os.path.getsize(file_path)
                    modified_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    
                    # Extract task_id from filename
                    task_id = filename.split('_')[1] if '_' in filename else "unknown"
                    
                    result_files.append({
                        "filename": filename,
                        "task_id": task_id,
                        "file_path": file_path,
                        "size": file_size,
                        "modified": modified_time.isoformat()
                    })
                except Exception as e:
                    logger.error(f"Failed to process result file {file_path}: {e}")
            
            # Sort by modification time (newest first)
            result_files.sort(key=lambda x: x["modified"], reverse=True)
            return result_files
            
        except Exception as e:
            logger.error(f"Failed to list result files: {e}")
            return []
    
    def get_results(self, task_id: str) -> Optional[Dict]:
        """Get translation results."""
        try:
            # Try Redis first
            results_key = f"results:{task_id}"
            results_data = redis_client.get(results_key)
            
            if results_data:
                return json.loads(results_data)
            
            # If not in Redis, try file system as fallback
            logger.info(f"Results not found in Redis for task {task_id}, trying file system...")
            return self.get_results_from_file(task_id)
            
        except Exception as e:
            logger.error(f"Failed to get results for task {task_id}: {e}")
            # Try file system as last resort
            try:
                return self.get_results_from_file(task_id)
            except Exception as file_error:
                logger.error(f"Failed to get results from file for task {task_id}: {file_error}")
                return None
    
    def get_translated_text(self, packed_data: Dict, language: str, text_id: str, source: str) -> Optional[str]:
        """
        Retrieves translated text from packed data structure.
        packed_data: The data structure returned by process_task.
        language: The target language (e.g., 'en', 'zh').
        text_id: The ID of the text segment.
        source: The source of the text ('TEXT', 'AUDIO', 'TRANSLATION').
        """
        try:
            return packed_data.get(language, {}).get(text_id, {}).get(source)
        except Exception as e:
            logger.error(f"Failed to retrieve translated text for {language}/{text_id}/{source}: {e}")
            return None
    
    def check_system_resources(self) -> Dict[str, float]:
        """Check system resource usage."""
        import psutil
        
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=1)
        
        return {
            "memory_usage": memory.percent,
            "cpu_usage": cpu,
            "memory_available": memory.available / (1024**3)  # GB
        }
    
    def is_system_healthy(self) -> bool:
        """Check if system has enough resources for processing."""
        resources = self.check_system_resources()
        return resources["memory_usage"] < settings.worker_memory_limit

# Global translation service instance
translation_service = TranslationService() 