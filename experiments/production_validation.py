#!/usr/bin/env python3
"""
WhisperTrans Production Validation
生产环境验证和风险评估
"""

import sys
import os
import time
import json
import asyncio
import aiohttp
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
import psutil
import redis
import whisper
import torch

# Add root to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from utils.config import settings
from infrastructure.redis_client import redis_client
from core.translation_service import translation_service
from utils.logger import get_logger

logger = get_logger("production_validation")

@dataclass
class ValidationResult:
    """验证结果"""
    component: str
    status: str  # "PASS", "FAIL", "WARNING"
    message: str
    details: Dict
    risk_level: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"

class ProductionValidator:
    """生产环境验证器"""
    
    def __init__(self):
        self.results: List[ValidationResult] = []
        self.session = None
    
    async def setup_session(self):
        """设置HTTP会话"""
        connector = aiohttp.TCPConnector(limit=10)
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        )
    
    async def cleanup_session(self):
        """清理HTTP会话"""
        if self.session:
            await self.session.close()
    
    def validate_system_resources(self) -> ValidationResult:
        """验证系统资源"""
        logger.info("Validating system resources...")
        
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        details = {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_available_gb": memory.available / (1024**3),
            "disk_percent": disk.percent,
            "disk_free_gb": disk.free / (1024**3)
        }
        
        # 评估标准
        if cpu_percent > 90:
            status, risk = "FAIL", "CRITICAL"
            message = f"CPU使用率过高: {cpu_percent}%"
        elif cpu_percent > 80:
            status, risk = "WARNING", "MEDIUM"
            message = f"CPU使用率较高: {cpu_percent}%"
        else:
            status, risk = "PASS", "LOW"
            message = f"CPU使用率正常: {cpu_percent}%"
        
        if memory.percent > 95:
            status, risk = "FAIL", "CRITICAL"
            message += f", 内存使用率过高: {memory.percent}%"
        elif memory.percent > 85:
            status, risk = "WARNING", "MEDIUM"
            message += f", 内存使用率较高: {memory.percent}%"
        else:
            message += f", 内存使用率正常: {memory.percent}%"
        
        if disk.percent > 95:
            status, risk = "FAIL", "CRITICAL"
            message += f", 磁盘空间不足: {disk.percent}%"
        elif disk.percent > 85:
            status, risk = "WARNING", "MEDIUM"
            message += f", 磁盘空间紧张: {disk.percent}%"
        else:
            message += f", 磁盘空间充足: {disk.percent}%"
        
        result = ValidationResult(
            component="system_resources",
            status=status,
            message=message,
            details=details,
            risk_level=risk
        )
        
        self.results.append(result)
        return result
    
    def validate_redis_connection(self) -> ValidationResult:
        """验证Redis连接"""
        logger.info("Validating Redis connection...")
        
        try:
            # 测试连接
            ping_result = redis_client.ping()
            info = redis_client.info()
            
            details = {
                "ping": ping_result,
                "redis_version": info.get("redis_version", "unknown"),
                "connected_clients": info.get("connected_clients", 0),
                "used_memory_human": info.get("used_memory_human", "unknown"),
                "total_commands_processed": info.get("total_commands_processed", 0)
            }
            
            if ping_result:
                status, risk = "PASS", "LOW"
                message = "Redis连接正常"
            else:
                status, risk = "FAIL", "CRITICAL"
                message = "Redis连接失败"
                
        except Exception as e:
            status, risk = "FAIL", "CRITICAL"
            message = f"Redis连接异常: {str(e)}"
            details = {"error": str(e)}
        
        result = ValidationResult(
            component="redis_connection",
            status=status,
            message=message,
            details=details,
            risk_level=risk
        )
        
        self.results.append(result)
        return result
    
    def validate_whisper_model(self) -> ValidationResult:
        """验证Whisper模型"""
        logger.info("Validating Whisper model...")
        
        try:
            start_time = time.time()
            model = whisper.load_model(settings.whisper_model, device="cpu")
            load_time = time.time() - start_time
            
            # 测试推理
            test_audio_path = "temp/uploads/test_audio.mp3"
            if os.path.exists(test_audio_path):
                start_time = time.time()
                result = model.transcribe(test_audio_path)
                inference_time = time.time() - start_time
                text_length = len(result["text"])
            else:
                inference_time = 0
                text_length = 0
            
            details = {
                "model_name": settings.whisper_model,
                "load_time_seconds": load_time,
                "inference_time_seconds": inference_time,
                "text_length": text_length,
                "device": "cpu"
            }
            
            if load_time > 30:  # 30秒
                status, risk = "WARNING", "MEDIUM"
                message = f"Whisper模型加载时间较长: {load_time:.2f}秒"
            else:
                status, risk = "PASS", "LOW"
                message = f"Whisper模型加载正常: {load_time:.2f}秒"
                
        except Exception as e:
            status, risk = "FAIL", "CRITICAL"
            message = f"Whisper模型加载失败: {str(e)}"
            details = {"error": str(e)}
        
        result = ValidationResult(
            component="whisper_model",
            status=status,
            message=message,
            details=details,
            risk_level=risk
        )
        
        self.results.append(result)
        return result
    
    def validate_gemini_api(self) -> ValidationResult:
        """验证Gemini API"""
        logger.info("Validating Gemini API...")
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.google_api_key)
            model = genai.GenerativeModel('gemini-pro')
            
            start_time = time.time()
            response = model.generate_content("Hello, test message.")
            response_time = time.time() - start_time
            
            details = {
                "api_key_configured": bool(settings.google_api_key),
                "response_time_seconds": response_time,
                "response_length": len(response.text),
                "model_name": "gemini-pro"
            }
            
            if response_time > 10:  # 10秒
                status, risk = "WARNING", "MEDIUM"
                message = f"Gemini API响应时间较长: {response_time:.2f}秒"
            else:
                status, risk = "PASS", "LOW"
                message = f"Gemini API响应正常: {response_time:.2f}秒"
                
        except Exception as e:
            status, risk = "FAIL", "CRITICAL"
            message = f"Gemini API验证失败: {str(e)}"
            details = {"error": str(e)}
        
        result = ValidationResult(
            component="gemini_api",
            status=status,
            message=message,
            details=details,
            risk_level=risk
        )
        
        self.results.append(result)
        return result
    
    async def validate_api_endpoints(self) -> ValidationResult:
        """验证API端点"""
        logger.info("Validating API endpoints...")
        
        endpoints = [
            "/api/v1/health/",
            "/api/v1/health/redis",
            "/api/v1/health/storage",
            "/api/v1/tasks/",
            "/api/v1/health/workers"
        ]
        
        failed_endpoints = []
        response_times = []
        
        for endpoint in endpoints:
            try:
                start_time = time.time()
                async with self.session.get(f"http://localhost:8000{endpoint}") as response:
                    response_time = time.time() - start_time
                    response_times.append(response_time)
                    
                    if response.status != 200:
                        failed_endpoints.append(f"{endpoint} (status: {response.status})")
                        
            except Exception as e:
                failed_endpoints.append(f"{endpoint} (error: {str(e)})")
        
        details = {
            "tested_endpoints": len(endpoints),
            "failed_endpoints": failed_endpoints,
            "avg_response_time": sum(response_times) / len(response_times) if response_times else 0,
            "max_response_time": max(response_times) if response_times else 0
        }
        
        if failed_endpoints:
            status, risk = "FAIL", "HIGH"
            message = f"API端点验证失败: {len(failed_endpoints)}/{len(endpoints)} 端点不可用"
        else:
            status, risk = "PASS", "LOW"
            message = f"所有API端点正常: {len(endpoints)}/{len(endpoints)}"
        
        result = ValidationResult(
            component="api_endpoints",
            status=status,
            message=message,
            details=details,
            risk_level=risk
        )
        
        self.results.append(result)
        return result
    
    def validate_storage_access(self) -> ValidationResult:
        """验证存储访问"""
        logger.info("Validating storage access...")
        
        try:
            from infrastructure.storage import storage_manager
            
            # 测试目录访问
            upload_dir = settings.upload_dir
            result_dir = settings.result_dir
            
            upload_exists = os.path.exists(upload_dir)
            result_exists = os.path.exists(result_dir)
            
            # 测试写入权限
            test_file = os.path.join(upload_dir, "test_write.tmp")
            try:
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
                write_permission = True
            except Exception:
                write_permission = False
            
            details = {
                "upload_dir_exists": upload_exists,
                "result_dir_exists": result_exists,
                "write_permission": write_permission,
                "upload_dir": upload_dir,
                "result_dir": result_dir
            }
            
            if not upload_exists or not result_exists:
                status, risk = "FAIL", "HIGH"
                message = "存储目录不存在"
            elif not write_permission:
                status, risk = "FAIL", "HIGH"
                message = "存储目录无写入权限"
            else:
                status, risk = "PASS", "LOW"
                message = "存储访问正常"
                
        except Exception as e:
            status, risk = "FAIL", "CRITICAL"
            message = f"存储验证失败: {str(e)}"
            details = {"error": str(e)}
        
        result = ValidationResult(
            component="storage_access",
            status=status,
            message=message,
            details=details,
            risk_level=risk
        )
        
        self.results.append(result)
        return result
    
    def validate_worker_health(self) -> ValidationResult:
        """验证Worker健康状态"""
        logger.info("Validating worker health...")
        
        try:
            # 检查Redis中的worker心跳
            worker_keys = redis_client.scan_iter(match="worker:*")
            active_workers = []
            
            current_time = time.time()
            for key in worker_keys:
                worker_data = redis_client.hgetall(key)
                if worker_data:
                    last_heartbeat = float(worker_data.get("last_heartbeat", 0))
                    if current_time - last_heartbeat < 300:  # 5分钟内有心跳
                        active_workers.append(key.decode())
            
            details = {
                "active_workers": len(active_workers),
                "worker_keys": [w.decode() for w in worker_keys],
                "current_time": current_time
            }
            
            if not active_workers:
                status, risk = "FAIL", "CRITICAL"
                message = "没有活跃的Worker"
            elif len(active_workers) < 1:
                status, risk = "WARNING", "MEDIUM"
                message = f"Worker数量较少: {len(active_workers)}"
            else:
                status, risk = "PASS", "LOW"
                message = f"Worker状态正常: {len(active_workers)} 个活跃Worker"
                
        except Exception as e:
            status, risk = "FAIL", "CRITICAL"
            message = f"Worker健康检查失败: {str(e)}"
            details = {"error": str(e)}
        
        result = ValidationResult(
            component="worker_health",
            status=status,
            message=message,
            details=details,
            risk_level=risk
        )
        
        self.results.append(result)
        return result
    
    def validate_security_config(self) -> ValidationResult:
        """验证安全配置"""
        logger.info("Validating security configuration...")
        
        security_issues = []
        details = {}
        
        # 检查API密钥
        if not settings.google_api_key or settings.google_api_key == "dummy_key_for_testing":
            security_issues.append("Google API密钥未配置或使用测试密钥")
        
        # 检查Redis配置
        if settings.redis_password == "":
            security_issues.append("Redis未设置密码")
        
        # 检查文件权限
        upload_dir = settings.upload_dir
        if os.path.exists(upload_dir):
            stat = os.stat(upload_dir)
            if stat.st_mode & 0o777 == 0o777:  # 777权限
                security_issues.append("上传目录权限过于开放")
        
        details = {
            "api_key_configured": bool(settings.google_api_key and settings.google_api_key != "dummy_key_for_testing"),
            "redis_password_set": bool(settings.redis_password),
            "upload_dir_permissions": oct(os.stat(upload_dir).st_mode)[-3:] if os.path.exists(upload_dir) else "N/A"
        }
        
        if security_issues:
            status, risk = "WARNING", "MEDIUM"
            message = f"发现 {len(security_issues)} 个安全问题"
        else:
            status, risk = "PASS", "LOW"
            message = "安全配置正常"
        
        result = ValidationResult(
            component="security_config",
            status=status,
            message=message,
            details=details,
            risk_level=risk
        )
        
        self.results.append(result)
        return result
    
    def generate_validation_report(self) -> Dict:
        """生成验证报告"""
        if not self.results:
            return {"error": "No validation results available"}
        
        # 统计结果
        total_checks = len(self.results)
        passed_checks = sum(1 for r in self.results if r.status == "PASS")
        failed_checks = sum(1 for r in self.results if r.status == "FAIL")
        warning_checks = sum(1 for r in self.results if r.status == "WARNING")
        
        # 风险等级统计
        critical_risks = sum(1 for r in self.results if r.risk_level == "CRITICAL")
        high_risks = sum(1 for r in self.results if r.risk_level == "HIGH")
        medium_risks = sum(1 for r in self.results if r.risk_level == "MEDIUM")
        low_risks = sum(1 for r in self.results if r.risk_level == "LOW")
        
        # 生产就绪性评估
        production_ready = (
            failed_checks == 0 and 
            critical_risks == 0 and 
            high_risks == 0
        )
        
        # 生成建议
        recommendations = self._generate_recommendations()
        
        return {
            "summary": {
                "total_checks": total_checks,
                "passed_checks": passed_checks,
                "failed_checks": failed_checks,
                "warning_checks": warning_checks,
                "critical_risks": critical_risks,
                "high_risks": high_risks,
                "medium_risks": medium_risks,
                "low_risks": low_risks,
                "production_ready": production_ready
            },
            "results": [asdict(r) for r in self.results],
            "recommendations": recommendations
        }
    
    def _generate_recommendations(self) -> List[str]:
        """生成建议"""
        recommendations = []
        
        for result in self.results:
            if result.status == "FAIL":
                if result.component == "redis_connection":
                    recommendations.append("修复Redis连接问题，确保Redis服务正常运行")
                elif result.component == "whisper_model":
                    recommendations.append("检查Whisper模型文件，确保模型正确安装")
                elif result.component == "gemini_api":
                    recommendations.append("配置有效的Google API密钥")
                elif result.component == "api_endpoints":
                    recommendations.append("启动API服务并检查端点配置")
                elif result.component == "storage_access":
                    recommendations.append("创建必要的存储目录并设置正确的权限")
                elif result.component == "worker_health":
                    recommendations.append("启动Worker进程并检查心跳机制")
            
            elif result.status == "WARNING":
                if result.component == "system_resources":
                    recommendations.append("监控系统资源使用，考虑增加硬件资源")
                elif result.component == "security_config":
                    recommendations.append("加强安全配置，设置API密钥和Redis密码")
        
        return recommendations

async def main():
    """主函数"""
    validator = ProductionValidator()
    
    try:
        await validator.setup_session()
        
        # 运行所有验证
        validator.validate_system_resources()
        validator.validate_redis_connection()
        validator.validate_whisper_model()
        validator.validate_gemini_api()
        await validator.validate_api_endpoints()
        validator.validate_storage_access()
        validator.validate_worker_health()
        validator.validate_security_config()
        
        # 生成报告
        report = validator.generate_validation_report()
        
        # 保存报告
        with open("experiments/production_validation_report.json", "w") as f:
            json.dump(report, f, indent=2)
        
        # 打印结果
        print("\n=== WhisperTrans Production Validation Results ===")
        summary = report.get("summary", {})
        print(f"Total checks: {summary.get('total_checks', 0)}")
        print(f"Passed: {summary.get('passed_checks', 0)}")
        print(f"Failed: {summary.get('failed_checks', 0)}")
        print(f"Warnings: {summary.get('warning_checks', 0)}")
        print(f"Production ready: {summary.get('production_ready', False)}")
        
        print("\nRisk levels:")
        print(f"Critical: {summary.get('critical_risks', 0)}")
        print(f"High: {summary.get('high_risks', 0)}")
        print(f"Medium: {summary.get('medium_risks', 0)}")
        print(f"Low: {summary.get('low_risks', 0)}")
        
        print("\nRecommendations:")
        for rec in report.get("recommendations", []):
            print(f"- {rec}")
    
    finally:
        await validator.cleanup_session()

if __name__ == "__main__":
    asyncio.run(main()) 