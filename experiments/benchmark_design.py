#!/usr/bin/env python3
"""
WhisperTrans Production Benchmark Design
数据驱动的实验方案来支撑生产环境设计决策
"""

import sys
import os
import time
import psutil
import json
import statistics
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
import asyncio
import aiohttp
import whisper
import torch
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor
import threading

# Add root to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from utils.config import settings
from core.translation_service import translation_service
from infrastructure.redis_client import redis_client
from utils.logger import get_logger

logger = get_logger("benchmark")

@dataclass
class BenchmarkResult:
    """基准测试结果"""
    test_name: str
    audio_duration: float  # 音频时长(秒)
    audio_size_mb: float   # 音频文件大小(MB)
    whisper_latency: float # Whisper推理时间(秒)
    whisper_memory_mb: float # Whisper内存使用(MB)
    gemini_latency: float  # Gemini推理时间(秒)
    gemini_memory_mb: float # Gemini内存使用(MB)
    total_latency: float   # 总处理时间(秒)
    stt_text_length: int   # STT文本长度
    translation_length: int # 翻译文本长度
    error_rate: float      # 错误率(0-1)
    throughput_per_hour: float # 每小时处理量
    cost_per_minute: float # 每分钟成本(估算)

class ProductionBenchmark:
    """生产环境基准测试"""
    
    def __init__(self):
        self.results: List[BenchmarkResult] = []
        self.test_audio_files = [
            "temp/uploads/short_30s.mp3",    # 30秒
            "temp/uploads/medium_2m.mp3",    # 2分钟
            "temp/uploads/long_5m.mp3",      # 5分钟
            "temp/uploads/very_long_10m.mp3" # 10分钟
        ]
        
    def measure_system_resources(self) -> Dict[str, float]:
        """测量系统资源使用"""
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            "cpu_percent": cpu_percent,
            "memory_percent": memory.percent,
            "memory_available_gb": memory.available / (1024**3),
            "disk_percent": disk.percent,
            "disk_free_gb": disk.free / (1024**3)
        }
    
    def measure_whisper_performance(self, audio_path: str) -> Dict[str, float]:
        """测量Whisper性能"""
        start_time = time.time()
        start_memory = psutil.Process().memory_info().rss / (1024**2)
        
        try:
            # 加载音频
            model = whisper.load_model(settings.whisper_model, device="cpu")
            result = model.transcribe(audio_path)
            
            end_time = time.time()
            end_memory = psutil.Process().memory_info().rss / (1024**2)
            
            return {
                "latency": end_time - start_time,
                "memory_used": end_memory - start_memory,
                "text_length": len(result["text"]),
                "segments_count": len(result["segments"])
            }
        except Exception as e:
            logger.error(f"Whisper benchmark failed: {e}")
            return {"latency": -1, "memory_used": 0, "text_length": 0, "segments_count": 0}
    
    def measure_gemini_performance(self, text: str, target_lang: str = "zh") -> Dict[str, float]:
        """测量Gemini性能"""
        start_time = time.time()
        start_memory = psutil.Process().memory_info().rss / (1024**2)
        
        try:
            genai.configure(api_key=settings.google_api_key)
            model = genai.GenerativeModel('gemini-pro')
            
            prompt = f"Translate the following text to {target_lang}:\n\n{text}"
            response = model.generate_content(prompt)
            translated_text = response.text
            
            end_time = time.time()
            end_memory = psutil.Process().memory_info().rss / (1024**2)
            
            return {
                "latency": end_time - start_time,
                "memory_used": end_memory - start_memory,
                "text_length": len(translated_text),
                "input_tokens": len(text.split()),
                "output_tokens": len(translated_text.split())
            }
        except Exception as e:
            logger.error(f"Gemini benchmark failed: {e}")
            return {"latency": -1, "memory_used": 0, "text_length": 0, "input_tokens": 0, "output_tokens": 0}
    
    def measure_protobuf_bandwidth(self, data: Dict) -> Dict[str, float]:
        """测量Protobuf序列化带宽"""
        import google.protobuf.json_format as json_format
        
        # 创建protobuf消息
        from experiments.proto import story_pb2
        
        start_time = time.time()
        
        # 序列化
        story_msg = story_pb2.StoryPack()
        story_msg.story_name = data.get("story_name", "")
        
        for lang, segments in data.get("languages", {}).items():
            lang_pack = story_msg.languages.add()
            lang_pack.lang = lang
            
            for seg in segments:
                text_seg = lang_pack.segments.add()
                text_seg.id = seg.get("id", "")
                text_seg.content = seg.get("content", "")
                text_seg.source = seg.get("source", "TEXT")
        
        serialized = story_msg.SerializeToString()
        end_time = time.time()
        
        return {
            "serialization_time": end_time - start_time,
            "size_bytes": len(serialized),
            "size_mb": len(serialized) / (1024**2),
            "compression_ratio": len(serialized) / len(json.dumps(data, ensure_ascii=False).encode())
        }
    
    def run_single_benchmark(self, audio_path: str, test_name: str) -> BenchmarkResult:
        """运行单个基准测试"""
        logger.info(f"Running benchmark: {test_name}")
        
        # 获取音频信息
        audio_size = os.path.getsize(audio_path) / (1024**2)  # MB
        
        # 测量Whisper性能
        whisper_result = self.measure_whisper_performance(audio_path)
        
        # 测量Gemini性能
        gemini_result = self.measure_gemini_performance(whisper_result.get("text", ""))
        
        # 计算总延迟
        total_latency = whisper_result.get("latency", 0) + gemini_result.get("latency", 0)
        
        # 计算吞吐量
        throughput_per_hour = 3600 / total_latency if total_latency > 0 else 0
        
        # 估算成本 (基于API调用)
        cost_per_minute = self.estimate_cost(whisper_result, gemini_result)
        
        result = BenchmarkResult(
            test_name=test_name,
            audio_duration=whisper_result.get("segments_count", 0) * 30,  # 估算时长
            audio_size_mb=audio_size,
            whisper_latency=whisper_result.get("latency", 0),
            whisper_memory_mb=whisper_result.get("memory_used", 0),
            gemini_latency=gemini_result.get("latency", 0),
            gemini_memory_mb=gemini_result.get("memory_used", 0),
            total_latency=total_latency,
            stt_text_length=whisper_result.get("text_length", 0),
            translation_length=gemini_result.get("text_length", 0),
            error_rate=0.0,  # 需要人工评估
            throughput_per_hour=throughput_per_hour,
            cost_per_minute=cost_per_minute
        )
        
        self.results.append(result)
        return result
    
    def estimate_cost(self, whisper_result: Dict, gemini_result: Dict) -> float:
        """估算处理成本"""
        # Whisper成本 (假设本地部署)
        whisper_cost = 0.0
        
        # Gemini成本 (基于token)
        input_tokens = gemini_result.get("input_tokens", 0)
        output_tokens = gemini_result.get("output_tokens", 0)
        
        # Gemini Pro定价 (示例)
        input_cost_per_1k = 0.0005  # $0.0005 per 1K input tokens
        output_cost_per_1k = 0.0015  # $0.0015 per 1K output tokens
        
        gemini_cost = (input_tokens * input_cost_per_1k / 1000) + (output_tokens * output_cost_per_1k / 1000)
        
        return whisper_cost + gemini_cost
    
    def run_comprehensive_benchmark(self) -> Dict[str, any]:
        """运行综合基准测试"""
        logger.info("Starting comprehensive benchmark...")
        
        # 系统资源基准
        system_baseline = self.measure_system_resources()
        
        # 运行所有测试
        for audio_file in self.test_audio_files:
            if os.path.exists(audio_file):
                test_name = f"benchmark_{Path(audio_file).stem}"
                self.run_single_benchmark(audio_file, test_name)
        
        # 分析结果
        analysis = self.analyze_results()
        
        # 生成报告
        report = {
            "system_baseline": system_baseline,
            "benchmark_results": [asdict(r) for r in self.results],
            "analysis": analysis,
            "recommendations": self.generate_recommendations(analysis)
        }
        
        return report
    
    def analyze_results(self) -> Dict[str, any]:
        """分析基准测试结果"""
        if not self.results:
            return {}
        
        latencies = [r.total_latency for r in self.results]
        memory_usage = [r.whisper_memory_mb + r.gemini_memory_mb for r in self.results]
        throughputs = [r.throughput_per_hour for r in self.results]
        costs = [r.cost_per_minute for r in self.results]
        
        return {
            "latency_stats": {
                "mean": statistics.mean(latencies),
                "median": statistics.median(latencies),
                "min": min(latencies),
                "max": max(latencies),
                "std": statistics.stdev(latencies) if len(latencies) > 1 else 0
            },
            "memory_stats": {
                "mean": statistics.mean(memory_usage),
                "max": max(memory_usage),
                "peak_usage_mb": max(memory_usage)
            },
            "throughput_stats": {
                "mean": statistics.mean(throughputs),
                "max": max(throughputs),
                "min": min(throughputs)
            },
            "cost_stats": {
                "mean_per_minute": statistics.mean(costs),
                "total_per_hour": sum(costs) * 60
            }
        }
    
    def generate_recommendations(self, analysis: Dict) -> List[str]:
        """基于分析结果生成建议"""
        recommendations = []
        
        # 延迟建议
        avg_latency = analysis.get("latency_stats", {}).get("mean", 0)
        if avg_latency > 300:  # 5分钟
            recommendations.append("考虑使用GPU加速Whisper推理")
            recommendations.append("实现音频分块处理以减少单次处理时间")
        
        # 内存建议
        peak_memory = analysis.get("memory_stats", {}).get("peak_usage_mb", 0)
        if peak_memory > 4096:  # 4GB
            recommendations.append("增加系统内存或实现内存管理策略")
            recommendations.append("考虑使用模型量化减少内存占用")
        
        # 吞吐量建议
        avg_throughput = analysis.get("throughput_stats", {}).get("mean", 0)
        if avg_throughput < 10:  # 每小时少于10个任务
            recommendations.append("增加worker节点数量")
            recommendations.append("实现任务并行处理")
        
        # 成本建议
        avg_cost = analysis.get("cost_stats", {}).get("mean_per_minute", 0)
        if avg_cost > 0.1:  # 每分钟超过$0.1
            recommendations.append("优化Gemini prompt减少token使用")
            recommendations.append("实现结果缓存减少重复翻译")
        
        return recommendations

def main():
    """主函数"""
    benchmark = ProductionBenchmark()
    report = benchmark.run_comprehensive_benchmark()
    
    # 保存报告
    with open("experiments/benchmark_report.json", "w") as f:
        json.dump(report, f, indent=2)
    
    # 打印关键指标
    print("\n=== WhisperTrans Production Benchmark Results ===")
    print(f"Total tests: {len(benchmark.results)}")
    
    if benchmark.results:
        avg_latency = statistics.mean([r.total_latency for r in benchmark.results])
        avg_memory = statistics.mean([r.whisper_memory_mb + r.gemini_memory_mb for r in benchmark.results])
        avg_throughput = statistics.mean([r.throughput_per_hour for r in benchmark.results])
        
        print(f"Average latency: {avg_latency:.2f}s")
        print(f"Average memory usage: {avg_memory:.2f}MB")
        print(f"Average throughput: {avg_throughput:.2f} tasks/hour")
        
        print("\nRecommendations:")
        for rec in report.get("recommendations", []):
            print(f"- {rec}")

if __name__ == "__main__":
    main() 