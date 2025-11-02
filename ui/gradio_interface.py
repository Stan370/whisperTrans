import sys
import os
from pathlib import Path

# Add the root directory to Python path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

import gradio as gr
import requests
import json
import time
from typing import Dict, List, Optional
from utils.config import settings

# API base URL
API_BASE_URL = f"http://{settings.api_host}:{settings.api_port}"

class TranslationUI:
    """Gradio interface for the translation system."""
    
    def __init__(self):
        self.api_base_url = API_BASE_URL
    
    def _make_api_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make API request with error handling."""
        try:
            url = f"{self.api_base_url}{endpoint}"
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": f"API request failed: {str(e)}"}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}
    
    def upload_and_translate(self, upload_files, source_lang, target_langs):
        """Upload ZIP or MP3/JSON files and create translation task."""
        if not upload_files:
            return "Please select at least one file to upload."
        try:
            # Prepare form data
            # Gradio returns a single file or a list depending on selection
            if not isinstance(upload_files, list):
                upload_files = [upload_files]
            files = [("files", (f.name, f, f.type if hasattr(f, 'type') else None)) for f in upload_files]
            data = {
                "source_language": source_lang,
                "target_languages": target_langs
            }
            response = self._make_api_request(
                "POST",
                "/api/v1/upload",
                files=files,
                data=data
            )
            if "error" in response:
                return f"Upload failed: {response['error']}"
            task_id = response.get("task_id")
            return f"Task created successfully! Task ID: {task_id}"
        except Exception as e:
            return f"Upload failed: {str(e)}"
    
    def check_task_status(self, task_id):
        """Check task status."""
        if not task_id:
            return "Please enter a task ID."
        
        try:
            response = self._make_api_request("GET", f"/api/v1/tasks/{task_id}")
            
            if "error" in response:
                return f"Status check failed: {response['error']}"
            
            status = response.get("status", "unknown")
            progress = response.get("progress", 0) * 100
            message = response.get("message", "")
            
            return f"Task Status: {status}\nProgress: {progress:.1f}%\n{message}"
            
        except Exception as e:
            return f"Status check failed: {str(e)}"
    
    def get_task_results(self, task_id):
        """Get task results."""
        if not task_id:
            return "Please enter a task ID."
        
        try:
            response = self._make_api_request("GET", f"/api/v1/tasks/{task_id}/results")
            
            if "error" in response:
                return f"Failed to get results: {response['error']}"
            
            # Format results for display
            formatted_results = json.dumps(response, indent=2, ensure_ascii=False)
            return formatted_results
            
        except Exception as e:
            return f"Failed to get results: {str(e)}"
    
    def cancel_task(self, task_id):
        """Cancel a task."""
        if not task_id:
            return "Please enter a task ID."
        
        try:
            response = self._make_api_request("POST", f"/api/v1/tasks/{task_id}/cancel")
            
            if "error" in response:
                return f"Cancel failed: {response['error']}"
            
            return f"Task {task_id} cancelled successfully."
            
        except Exception as e:
            return f"Cancel failed: {str(e)}"
    
    def retry_task(self, task_id):
        """Retry a failed task."""
        if not task_id:
            return "Please enter a task ID."
        
        try:
            response = self._make_api_request("POST", f"/api/v1/tasks/{task_id}/retry")
            
            if "error" in response:
                return f"Retry failed: {response['error']}"
            
            return f"Task {task_id} retried successfully."
            
        except Exception as e:
            return f"Retry failed: {str(e)}"
    
    def list_tasks(self, status_filter):
        """List all tasks."""
        try:
            params = {"status": status_filter} if status_filter else {}
            response = self._make_api_request("GET", "/api/v1/tasks", params=params)
            
            if "error" in response:
                return f"Failed to list tasks: {response['error']}"
            
            # Format task list for display
            if not response:
                return "No tasks found."
            
            formatted_tasks = []
            for task in response:
                formatted_tasks.append({
                    "Task ID": task.get("task_id"),
                    "Status": task.get("status"),
                    "Progress": f"{task.get('progress', 0) * 100:.1f}%",
                    "Created": task.get("created_at"),
                    "Updated": task.get("updated_at")
                })
            
            return json.dumps(formatted_tasks, indent=2, ensure_ascii=False)
            
        except Exception as e:
            return f"Failed to list tasks: {str(e)}"
    
    def get_system_health(self):
        """Get system health information."""
        try:
            response = self._make_api_request("GET", "/api/v1/health")
            
            if "error" in response:
                return f"Health check failed: {response['error']}"
            
            # Format health info for display
            health_info = {
                "Status": response.get("status", "unknown"),
                "Memory Usage": f"{response.get('memory_usage', 0):.1f}%",
                "Redis Connected": response.get("redis_connected", False),
                "Storage Available": response.get("storage_available", False),
                "Timestamp": response.get("timestamp")
            }
            
            return json.dumps(health_info, indent=2, ensure_ascii=False)
            
        except Exception as e:
            return f"Health check failed: {str(e)}"
    
    def get_system_metrics(self):
        """Get system metrics."""
        try:
            response = self._make_api_request("GET", "/api/v1/health/metrics")
            
            if "error" in response:
                return f"Metrics check failed: {response['error']}"
            
            # Format metrics for display
            return json.dumps(response, indent=2, ensure_ascii=False)
            
        except Exception as e:
            return f"Metrics check failed: {str(e)}"
    
    def create_interface(self):
        """Create the Gradio interface."""
        with gr.Blocks(title="Multilingual Story Translation System") as demo:
            gr.Markdown("# Multilingual Story Translation System")
            gr.Markdown("Upload a ZIP file, or MP3/JSON files, to translate your storybook.")
            
            with gr.Tab("Upload & Translate"):
                with gr.Row():
                    with gr.Column():
                        upload_files = gr.File(
                            label="Upload ZIP, MP3, or JSON files",
                            file_types=[".zip", ".mp3", ".json"],
                            file_count="multiple"
                        )
                        source_lang = gr.Dropdown(
                            choices=["en", "zh", "ja", "ko", "fr", "de", "es"],
                            value="en",
                            label="Source Language"
                        )
                        target_langs = gr.CheckboxGroup(
                            choices=["zh", "ja", "ko", "fr", "de", "es"],
                            value=["zh", "ja"],
                            label="Target Languages"
                        )
                        upload_btn = gr.Button("Upload and Start Translation", variant="primary")
                        upload_output = gr.Textbox(label="Upload Result", lines=3)
                
                upload_btn.click(
                    self.upload_and_translate,
                    inputs=[upload_files, source_lang, target_langs],
                    outputs=upload_output
                )
            
            with gr.Tab("Task Management"):
                with gr.Row():
                    with gr.Column():
                        task_id_input = gr.Textbox(label="Task ID")
                        status_btn = gr.Button("Check Status")
                        status_output = gr.Textbox(label="Task Status", lines=5)
                        
                        results_btn = gr.Button("Get Results")
                        results_output = gr.Textbox(label="Translation Results", lines=10)
                        
                        cancel_btn = gr.Button("Cancel Task", variant="stop")
                        cancel_output = gr.Textbox(label="Cancel Result", lines=2)
                        
                        retry_btn = gr.Button("Retry Task")
                        retry_output = gr.Textbox(label="Retry Result", lines=2)
                
                status_btn.click(
                    self.check_task_status,
                    inputs=task_id_input,
                    outputs=status_output
                )
                
                results_btn.click(
                    self.get_task_results,
                    inputs=task_id_input,
                    outputs=results_output
                )
                
                cancel_btn.click(
                    self.cancel_task,
                    inputs=task_id_input,
                    outputs=cancel_output
                )
                
                retry_btn.click(
                    self.retry_task,
                    inputs=task_id_input,
                    outputs=retry_output
                )
            
            with gr.Tab("Task List"):
                with gr.Row():
                    with gr.Column():
                        list_status = gr.Dropdown(
                            choices=["", "pending", "processing", "completed", "failed", "cancelled"],
                            label="Filter by Status (optional)"
                        )
                        list_btn = gr.Button("List Tasks")
                        list_output = gr.Textbox(label="Tasks List", lines=15)
                
                list_btn.click(
                    self.list_tasks,
                    inputs=list_status,
                    outputs=list_output
                )
            
            with gr.Tab("System Health"):
                with gr.Row():
                    with gr.Column():
                        health_btn = gr.Button("Check Health")
                        health_output = gr.Textbox(label="System Health", lines=10)
                        
                        metrics_btn = gr.Button("Get Metrics")
                        metrics_output = gr.Textbox(label="System Metrics", lines=15)
                
                health_btn.click(
                    self.get_system_health,
                    outputs=health_output
                )
                
                metrics_btn.click(
                    self.get_system_metrics,
                    outputs=metrics_output
                )
        
        return demo

def main():
    """Main entry point for the Gradio interface."""
    ui = TranslationUI()
    demo = ui.create_interface()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=True
    )
    demo.launch(share=True) 

if __name__ == "__main__":
    main() 