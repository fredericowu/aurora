#!/usr/bin/env python3
"""
Performance testing script for the search API.
Tests Lambda function with same and random search strings.
Excludes first warm-up call from results.
"""

import os
import sys
import time
import statistics
import requests
import random
import string
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlencode

# Configuration
API_BASE_URL = os.getenv('API_BASE_URL', '')
NUM_ITERATIONS = 10
WARMUP_CALLS = 1


def generate_random_string(length: int = 10) -> str:
    """Generate a random search string."""
    words = [
        'test', 'search', 'message', 'query', 'data', 'api', 'lambda',
        'database', 'postgres', 'aws', 'cloud', 'server', 'client',
        'request', 'response', 'endpoint', 'function', 'service'
    ]
    return ' '.join(random.choices(words, k=random.randint(1, 3)))


def make_search_request(url: str, query: str) -> Dict:
    """
    Make a search request and return timing information.
    
    Returns:
        Dict with 'success', 'latency_ms', 'status_code', 'error'
    """
    start_time = time.time()
    
    try:
        params = {'q': query, 'page': 0, 'limit': 10}
        response = requests.get(url, params=params, timeout=30)
        elapsed_ms = (time.time() - start_time) * 1000
        
        return {
            'success': response.status_code == 200,
            'latency_ms': elapsed_ms,
            'status_code': response.status_code,
            'error': None if response.status_code == 200 else f"HTTP {response.status_code}"
        }
    except requests.exceptions.RequestException as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return {
            'success': False,
            'latency_ms': elapsed_ms,
            'status_code': None,
            'error': str(e)
        }


def calculate_statistics(latencies: List[float]) -> Dict:
    """Calculate statistical metrics from latency data."""
    if not latencies:
        return {}
    
    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)
    
    return {
        'min': min(latencies),
        'max': max(latencies),
        'mean': statistics.mean(latencies),
        'median': statistics.median(latencies),
        'p50': sorted_latencies[int(n * 0.50)] if n > 0 else None,
        'p95': sorted_latencies[int(n * 0.95)] if n > 1 else sorted_latencies[0],
        'p99': sorted_latencies[int(n * 0.99)] if n > 1 else sorted_latencies[0],
        'stdev': statistics.stdev(latencies) if len(latencies) > 1 else 0
    }


def run_test_suite(api_url: str, test_name: str, queries: List[str]) -> Dict:
    """
    Run a test suite with given queries.
    
    Args:
        api_url: API endpoint URL
        test_name: Name of the test suite
        queries: List of search queries to use
        
    Returns:
        Dict with test results and statistics
    """
    print(f"\n{'='*60}")
    print(f"Running: {test_name}")
    print(f"{'='*60}")
    
    results = []
    latencies = []
    
    # Warm-up call (excluded from results)
    print(f"\nWarm-up call (excluded from results)...")
    warmup_query = queries[0] if queries else "test"
    warmup_result = make_search_request(api_url, warmup_query)
    error_msg = warmup_result.get('error') or 'OK'
    print(f"Warm-up: {warmup_result['latency_ms']:.2f}ms - {error_msg}")
    
    # Actual test calls
    print(f"\nRunning {NUM_ITERATIONS} test calls...")
    for i, query in enumerate(queries[:NUM_ITERATIONS], 1):
        result = make_search_request(api_url, query)
        results.append(result)
        
        if result['success']:
            latencies.append(result['latency_ms'])
            status = "✓"
        else:
            status = "✗"
        
        error_msg = result.get('error') or 'OK'
        print(f"  [{i:2d}] {status} {result['latency_ms']:7.2f}ms - Query: '{query[:30]}...' ({error_msg})")
    
    # Calculate statistics
    successful_results = [r for r in results if r['success']]
    success_rate = len(successful_results) / len(results) * 100 if results else 0
    
    stats = calculate_statistics(latencies) if latencies else {}
    
    print(f"\nResults Summary:")
    print(f"  Total requests: {len(results)}")
    print(f"  Successful: {len(successful_results)} ({success_rate:.1f}%)")
    print(f"  Failed: {len(results) - len(successful_results)}")
    
    if stats:
        print(f"\nLatency Statistics (ms):")
        print(f"  Min:    {stats['min']:.2f}")
        print(f"  Max:    {stats['max']:.2f}")
        print(f"  Mean:   {stats['mean']:.2f}")
        print(f"  Median: {stats['median']:.2f}")
        print(f"  P50:    {stats['p50']:.2f}")
        print(f"  P95:    {stats['p95']:.2f}")
        print(f"  P99:    {stats['p99']:.2f}")
        print(f"  StdDev: {stats['stdev']:.2f}")
    
    return {
        'test_name': test_name,
        'total_requests': len(results),
        'successful_requests': len(successful_results),
        'failed_requests': len(results) - len(successful_results),
        'success_rate': success_rate,
        'statistics': stats,
        'results': results
    }


def main():
    """Main performance test function."""
    api_url = API_BASE_URL.rstrip('/')
    
    if not api_url:
        print("Error: API_BASE_URL environment variable not set")
        print("Usage: API_BASE_URL=https://your-api.execute-api.region.amazonaws.com python performance_test.py")
        sys.exit(1)
    
    # Ensure URL ends with /search
    if not api_url.endswith('/search'):
        api_url = urljoin(api_url, '/search')
    
    print(f"Performance Test for Aurora Search API")
    print(f"API URL: {api_url}")
    print(f"Iterations per test: {NUM_ITERATIONS}")
    print(f"Warm-up calls: {WARMUP_CALLS}")
    
    # Test 1: Same search string (10 times)
    same_query = "test search"
    same_queries = [same_query] * (NUM_ITERATIONS + WARMUP_CALLS)
    test1_results = run_test_suite(api_url, "Same Search String Test", same_queries)
    
    # Test 2: Random search strings (10 times)
    random_queries = [generate_random_string() for _ in range(NUM_ITERATIONS + WARMUP_CALLS)]
    test2_results = run_test_suite(api_url, "Random Search Strings Test", random_queries)
    
    # Overall summary
    print(f"\n{'='*60}")
    print("Overall Summary")
    print(f"{'='*60}")
    
    print(f"\nSame Search String Test:")
    if test1_results['statistics']:
        stats = test1_results['statistics']
        print(f"  Mean latency: {stats['mean']:.2f}ms")
        print(f"  P95 latency:  {stats['p95']:.2f}ms")
        print(f"  Success rate: {test1_results['success_rate']:.1f}%")
    
    print(f"\nRandom Search Strings Test:")
    if test2_results['statistics']:
        stats = test2_results['statistics']
        print(f"  Mean latency: {stats['mean']:.2f}ms")
        print(f"  P95 latency:  {stats['p95']:.2f}ms")
        print(f"  Success rate: {test2_results['success_rate']:.1f}%")
    
    # Check if requirements are met
    print(f"\n{'='*60}")
    print("Performance Requirements Check")
    print(f"{'='*60}")
    
    all_stats = []
    if test1_results['statistics']:
        all_stats.append(test1_results['statistics'])
    if test2_results['statistics']:
        all_stats.append(test2_results['statistics'])
    
    if all_stats:
        max_p95 = max(s['p95'] for s in all_stats if s.get('p95'))
        max_mean = max(s['mean'] for s in all_stats if s.get('mean'))
        
        print(f"  Max P95 latency: {max_p95:.2f}ms")
        print(f"  Max mean latency: {max_mean:.2f}ms")
        
        if max_p95 < 100:
            print(f"  ✓ Requirement met: P95 < 100ms")
        else:
            print(f"  ✗ Requirement NOT met: P95 >= 100ms")
        
        if max_mean < 100:
            print(f"  ✓ Requirement met: Mean < 100ms")
        else:
            print(f"  ✗ Requirement NOT met: Mean >= 100ms")
    
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()

