import os
import time
import whisper
import torch
from typing import Dict, List, Optional
import google.generativeai as genai
from config import settings, LANGUAGE_MAP
from core.models import TranslationTask, TranslationResult, TaskStatus
from utils.logger import get_logger

logger = get_logger("translation_service")

class TranslationService:
    """Centralized translation service for STT and translation processing."""
    
    def __init__(self):
        self.whisper_model = None
        self.gemini_model = None
        self._setup_models()
    
    def _setup_models(self):
        """Setup Whisper and Gemini models."""
        try:
            # Setup Whisper model
            device = self._get_device()
            self.whisper_model = whisper.load_model(settings.whisper_model, device=device)
            logger.info(f"Whisper model loaded: {settings.whisper_model} on {device}")
            
            # Setup Gemini model
            genai.configure(api_key=settings.google_api_key)
            self.gemini_model = genai.GenerativeModel('gemini-2.0-flash')
            logger.info("Gemini model configured successfully")
            
        except Exception as e:
            logger.error(f"Failed to setup models: {e}")
            raise
    
    def _get_device(self) -> str:
        """Get the best available device for Whisper."""
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        elif torch.cuda.is_available():
            return "cuda"
        else:
            return "cpu"
    
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
    
    def transcribe_audio(self, audio_file: str) -> str:
        """Transcribe audio file using Whisper model."""
        try:
            start_time = time.time()
            result = self.whisper_model.transcribe(audio_file)
            processing_time = time.time() - start_time
            
            logger.info(f"Transcribed {audio_file} in {processing_time:.2f}s")
            return result["text"].strip()
            
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
                          target_languages: List[str]) -> TranslationResult:
        """Process a single audio file through STT and translation."""
        start_time = time.time()
        
        try:
            # Step 1: Transcribe audio
            stt_text = self.transcribe_audio(audio_file)
            
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
            
            # Create result
            result = TranslationResult(
                task_id="",  # Will be set by caller
                file_id=file_id,
                original_text=reference_text,
                stt_text=stt_text,
                wer=wer,
                validated_text=validated_text,
                translations=translations,
                processing_time=processing_time
            )
            
            logger.info(f"Processed {file_id} in {processing_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"Failed to process {file_id}: {e}")
            raise
    
    def process_task(self, task: TranslationTask) -> Dict[str, TranslationResult]:
        """Process a complete translation task."""
        results = {}
        
        try:
            logger.info(f"Starting to process task {task.task_id}")
            
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
                
                # Set task_id in result
                result.task_id = task.task_id
                results[file_id] = result
                
                logger.info(f"Completed {i+1}/{len(task.audio_files)} files for task {task.task_id}")
            
            logger.info(f"Successfully processed task {task.task_id}")
            return results
            
        except Exception as e:
            logger.error(f"Failed to process task {task.task_id}: {e}")
            raise
    
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