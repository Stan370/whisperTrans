#!/usr/bin/env python3
"""
WhisperTrans Load Testing
生产环境负载测试和性能验证
"""

import sys
import os
import time
import asyncio
import aiohttp
import json
import statistics
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
import threading
from concurrent.futures import ThreadPoolExecutor
import psutil

# Add root to path
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir))

from utils.config import settings
from utils.logger import get_logger

logger = get_logger("load_test")

@dataclass
class LoadTestResult:
    """负载测试结果"""
    test_name: str
    concurrent_users: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_response_time: float
    min_response_time: float
    max_response_time: float
    p95_response_time: float
    p99_response_time: float
    requests_per_second: float
    error_rate: float
    cpu_usage: float
    memory_usage: float

class LoadTester:
    """负载测试器"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results: List[LoadTestResult] = []
        self.session = None
        
    async def setup_session(self):
        """设置HTTP会话"""
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=50)
        timeout = aiohttp.ClientTimeout(total=300)  # 5分钟超时
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout
        )
    
    async def cleanup_session(self):
        """清理HTTP会话"""
        if self.session:
            await self.session.close()
    
    async def make_request(self, endpoint: str, method: str = "GET", **kwargs) -> Tuple[bool, float, int]:
        """发送单个请求"""
        start_time = time.time()
        success = False
        status_code = 0
        
        try:
            if method == "GET":
                async with self.session.get(f"{self.base_url}{endpoint}") as response:
                    status_code = response.status
                    success = response.status == 200
            elif method == "POST":
                async with self.session.post(f"{self.base_url}{endpoint}", **kwargs) as response:
                    status_code = response.status
                    success = response.status in [200, 201]
            elif method == "PUT":
                async with self.session.put(f"{self.base_url}{endpoint}", **kwargs) as response:
                    status_code = response.status
                    success = response.status == 200
            elif method == "DELETE":
                async with self.session.delete(f"{self.base_url}{endpoint}") as response:
                    status_code = response.status
                    success = response.status == 200
                    
        except Exception as e:
            logger.error(f"Request failed: {e}")
            success = False
            status_code = 0
        
        response_time = time.time() - start_time
        return success, response_time, status_code
    
    async def health_check_test(self, concurrent_users: int, duration: int = 60) -> LoadTestResult:
        """健康检查负载测试"""
        logger.info(f"Starting health check test with {concurrent_users} concurrent users")
        
        start_time = time.time()
        end_time = start_time + duration
        request_times = []
        successful_requests = 0
        failed_requests = 0
        
        # 启动并发任务
        tasks = []
        for _ in range(concurrent_users):
            task = asyncio.create_task(self._health_check_worker(end_time, request_times))
            tasks.append(task)
        
        # 等待所有任务完成
        await asyncio.gather(*tasks)
        
        # 计算统计信息
        total_requests = len(request_times)
        successful_requests = sum(1 for success, _, _ in request_times if success)
        failed_requests = total_requests - successful_requests
        
        response_times = [rt for _, rt, _ in request_times if rt > 0]
        
        if response_times:
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            p95_response_time = statistics.quantiles(response_times, n=20)[18] if len(response_times) >= 20 else max_response_time
            p99_response_time = statistics.quantiles(response_times, n=100)[98] if len(response_times) >= 100 else max_response_time
        else:
            avg_response_time = min_response_time = max_response_time = p95_response_time = p99_response_time = 0
        
        requests_per_second = total_requests / duration
        error_rate = failed_requests / total_requests if total_requests > 0 else 0
        
        # 系统资源使用
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_usage = psutil.virtual_memory().percent
        
        result = LoadTestResult(
            test_name="health_check",
            concurrent_users=concurrent_users,
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            avg_response_time=avg_response_time,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            p95_response_time=p95_response_time,
            p99_response_time=p99_response_time,
            requests_per_second=requests_per_second,
            error_rate=error_rate,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage
        )
        
        self.results.append(result)
        return result
    
    async def _health_check_worker(self, end_time: float, request_times: List):
        """健康检查工作线程"""
        while time.time() < end_time:
            success, response_time, status_code = await self.make_request("/api/v1/health/")
            request_times.append((success, response_time, status_code))
            await asyncio.sleep(0.1)  # 100ms间隔
    
    async def task_creation_test(self, concurrent_users: int, duration: int = 60) -> LoadTestResult:
        """任务创建负载测试"""
        logger.info(f"Starting task creation test with {concurrent_users} concurrent users")
        
        start_time = time.time()
        end_time = start_time + duration
        request_times = []
        successful_requests = 0
        failed_requests = 0
        
        # 准备测试文件
        test_files = self._prepare_test_files()
        
        # 启动并发任务
        tasks = []
        for i in range(concurrent_users):
            test_file = test_files[i % len(test_files)]
            task = asyncio.create_task(self._task_creation_worker(end_time, request_times, test_file))
            tasks.append(task)
        
        # 等待所有任务完成
        await asyncio.gather(*tasks)
        
        # 计算统计信息 (类似health_check_test)
        total_requests = len(request_times)
        successful_requests = sum(1 for success, _, _ in request_times if success)
        failed_requests = total_requests - successful_requests
        
        response_times = [rt for _, rt, _ in request_times if rt > 0]
        
        if response_times:
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            p95_response_time = statistics.quantiles(response_times, n=20)[18] if len(response_times) >= 20 else max_response_time
            p99_response_time = statistics.quantiles(response_times, n=100)[98] if len(response_times) >= 100 else max_response_time
        else:
            avg_response_time = min_response_time = max_response_time = p95_response_time = p99_response_time = 0
        
        requests_per_second = total_requests / duration
        error_rate = failed_requests / total_requests if total_requests > 0 else 0
        
        # 系统资源使用
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_usage = psutil.virtual_memory().percent
        
        result = LoadTestResult(
            test_name="task_creation",
            concurrent_users=concurrent_users,
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            avg_response_time=avg_response_time,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            p95_response_time=p95_response_time,
            p99_response_time=p99_response_time,
            requests_per_second=requests_per_second,
            error_rate=error_rate,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage
        )
        
        self.results.append(result)
        return result
    
    async def _task_creation_worker(self, end_time: float, request_times: List, test_file: str):
        """任务创建工作线程"""
        while time.time() < end_time:
            data = aiohttp.FormData()
            data.add_field('files', open(test_file, 'rb'), filename=os.path.basename(test_file))
            data.add_field('source_language', 'en')
            data.add_field('target_languages', 'zh')
            
            success, response_time, status_code = await self.make_request(
                "/api/v1/tasks/", 
                method="POST", 
                data=data
            )
            request_times.append((success, response_time, status_code))
            await asyncio.sleep(1)  # 1秒间隔，避免过载
    
    def _prepare_test_files(self) -> List[str]:
        """准备测试文件"""
        test_files = []
        upload_dir = "temp/uploads"
        
        if os.path.exists(upload_dir):
            for file in os.listdir(upload_dir):
                if file.endswith('.mp3'):
                    test_files.append(os.path.join(upload_dir, file))
        
        # 如果没有测试文件，创建模拟文件
        if not test_files:
            logger.warning("No test files found, creating mock files")
            os.makedirs(upload_dir, exist_ok=True)
            # 这里可以创建一些小的测试音频文件
            test_files = [os.path.join(upload_dir, "test1.mp3")]
        
        return test_files
    
    async def story_query_test(self, concurrent_users: int, duration: int = 60) -> LoadTestResult:
        """故事查询负载测试"""
        logger.info(f"Starting story query test with {concurrent_users} concurrent users")
        
        # 首先创建一些测试任务
        await self._create_test_stories()
        
        start_time = time.time()
        end_time = start_time + duration
        request_times = []
        successful_requests = 0
        failed_requests = 0
        
        # 启动并发任务
        tasks = []
        for i in range(concurrent_users):
            task = asyncio.create_task(self._story_query_worker(end_time, request_times, i))
            tasks.append(task)
        
        # 等待所有任务完成
        await asyncio.gather(*tasks)
        
        # 计算统计信息 (类似其他测试)
        total_requests = len(request_times)
        successful_requests = sum(1 for success, _, _ in request_times if success)
        failed_requests = total_requests - successful_requests
        
        response_times = [rt for _, rt, _ in request_times if rt > 0]
        
        if response_times:
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
            p95_response_time = statistics.quantiles(response_times, n=20)[18] if len(response_times) >= 20 else max_response_time
            p99_response_time = statistics.quantiles(response_times, n=100)[98] if len(response_times) >= 100 else max_response_time
        else:
            avg_response_time = min_response_time = max_response_time = p95_response_time = p99_response_time = 0
        
        requests_per_second = total_requests / duration
        error_rate = failed_requests / total_requests if total_requests > 0 else 0
        
        # 系统资源使用
        cpu_usage = psutil.cpu_percent(interval=1)
        memory_usage = psutil.virtual_memory().percent
        
        result = LoadTestResult(
            test_name="story_query",
            concurrent_users=concurrent_users,
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            avg_response_time=avg_response_time,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            p95_response_time=p95_response_time,
            p99_response_time=p99_response_time,
            requests_per_second=requests_per_second,
            error_rate=error_rate,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage
        )
        
        self.results.append(result)
        return result
    
    async def _story_query_worker(self, end_time: float, request_times: List, worker_id: int):
        """故事查询工作线程"""
        story_names = ["test_story_1", "test_story_2", "test_story_3"]
        languages = ["en", "zh"]
        sources = ["TEXT", "AUDIO", "TRANSLATION"]
        
        while time.time() < end_time:
            story_name = story_names[worker_id % len(story_names)]
            lang = languages[worker_id % len(languages)]
            source = sources[worker_id % len(sources)]
            text_id = f"segment_{worker_id % 10}"
            
            endpoint = f"/api/v1/story/{story_name}/text?lang={lang}&text_id={text_id}&source={source}"
            success, response_time, status_code = await self.make_request(endpoint)
            request_times.append((success, response_time, status_code))
            await asyncio.sleep(0.5)  # 500ms间隔
    
    async def _create_test_stories(self):
        """创建测试故事"""
        # 这里可以创建一些测试故事数据
        logger.info("Creating test stories for query testing")
        # 实现测试故事创建逻辑
    
    def generate_report(self) -> Dict:
        """生成负载测试报告"""
        if not self.results:
            return {"error": "No test results available"}
        
        # 按测试类型分组
        test_groups = {}
        for result in self.results:
            if result.test_name not in test_groups:
                test_groups[result.test_name] = []
            test_groups[result.test_name].append(result)
        
        # 分析每个测试类型
        analysis = {}
        for test_name, results in test_groups.items():
            analysis[test_name] = {
                "total_tests": len(results),
                "avg_response_time": statistics.mean([r.avg_response_time for r in results]),
                "max_response_time": max([r.max_response_time for r in results]),
                "avg_throughput": statistics.mean([r.requests_per_second for r in results]),
                "avg_error_rate": statistics.mean([r.error_rate for r in results]),
                "scalability": self._calculate_scalability(results)
            }
        
        # 生成建议
        recommendations = self._generate_recommendations(analysis)
        
        return {
            "test_results": [asdict(r) for r in self.results],
            "analysis": analysis,
            "recommendations": recommendations,
            "summary": self._generate_summary(analysis)
        }
    
    def _calculate_scalability(self, results: List[LoadTestResult]) -> Dict:
        """计算可扩展性指标"""
        if len(results) < 2:
            return {"linear": True, "efficiency": 1.0}
        
        # 按并发用户数排序
        sorted_results = sorted(results, key=lambda x: x.concurrent_users)
        
        # 计算吞吐量效率
        throughputs = [r.requests_per_second for r in sorted_results]
        users = [r.concurrent_users for r in sorted_results]
        
        # 理想线性增长
        ideal_throughput = throughputs[0] * (users[-1] / users[0])
        actual_throughput = throughputs[-1]
        
        efficiency = actual_throughput / ideal_throughput if ideal_throughput > 0 else 0
        
        return {
            "linear": efficiency > 0.8,  # 80%以上认为是线性的
            "efficiency": efficiency,
            "throughput_growth": throughputs[-1] / throughputs[0] if throughputs[0] > 0 else 0
        }
    
    def _generate_recommendations(self, analysis: Dict) -> List[str]:
        """生成建议"""
        recommendations = []
        
        for test_name, stats in analysis.items():
            avg_response_time = stats.get("avg_response_time", 0)
            avg_error_rate = stats.get("avg_error_rate", 0)
            efficiency = stats.get("scalability", {}).get("efficiency", 1.0)
            
            if avg_response_time > 5.0:  # 5秒
                recommendations.append(f"{test_name}: 响应时间过长，考虑优化API性能")
            
            if avg_error_rate > 0.05:  # 5%错误率
                recommendations.append(f"{test_name}: 错误率过高，检查系统稳定性")
            
            if efficiency < 0.8:
                recommendations.append(f"{test_name}: 可扩展性不足，考虑增加资源或优化架构")
        
        return recommendations
    
    def _generate_summary(self, analysis: Dict) -> Dict:
        """生成总结"""
        total_tests = sum(stats.get("total_tests", 0) for stats in analysis.values())
        avg_response_times = [stats.get("avg_response_time", 0) for stats in analysis.values()]
        avg_error_rates = [stats.get("avg_error_rate", 0) for stats in analysis.values()]
        
        return {
            "total_tests": total_tests,
            "overall_avg_response_time": statistics.mean(avg_response_times) if avg_response_times else 0,
            "overall_avg_error_rate": statistics.mean(avg_error_rates) if avg_error_rates else 0,
            "production_ready": all(stats.get("avg_error_rate", 0) < 0.05 for stats in analysis.values())
        }

async def main():
    """主函数"""
    # 创建负载测试器
    load_tester = LoadTester()
    
    try:
        await load_tester.setup_session()
        
        # 运行不同类型的负载测试
        test_configs = [
            {"concurrent_users": 10, "duration": 60},
            {"concurrent_users": 50, "duration": 60},
            {"concurrent_users": 100, "duration": 60}
        ]
        
        for config in test_configs:
            # 健康检查测试
            await load_tester.health_check_test(**config)
            
            # 任务创建测试
            await load_tester.task_creation_test(**config)
            
            # 故事查询测试
            await load_tester.story_query_test(**config)
        
        # 生成报告
        report = load_tester.generate_report()
        
        # 保存报告
        with open("experiments/load_test_report.json", "w") as f:
            json.dump(report, f, indent=2)
        
        # 打印关键指标
        print("\n=== WhisperTrans Load Test Results ===")
        summary = report.get("summary", {})
        print(f"Total tests: {summary.get('total_tests', 0)}")
        print(f"Overall avg response time: {summary.get('overall_avg_response_time', 0):.2f}s")
        print(f"Overall avg error rate: {summary.get('overall_avg_error_rate', 0):.2%}")
        print(f"Production ready: {summary.get('production_ready', False)}")
        
        print("\nRecommendations:")
        for rec in report.get("recommendations", []):
            print(f"- {rec}")
    
    finally:
        await load_tester.cleanup_session()

if __name__ == "__main__":
    asyncio.run(main()) 