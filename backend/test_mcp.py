#!/usr/bin/env python3
"""
Test script for MCP tools - validates all endpoints are working
"""

import requests
import json
import sys

BASE_URL = "http://localhost:5001"
API_KEY = "secret123"
HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY
}


def test_health():
    """Test /api/health endpoint"""
    print("\n🏥 Testing /api/health...")
    try:
        r = requests.get(f"{BASE_URL}/api/health", timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"✅ Health check passed: {data.get('status')}")
            print(f"   Agent: {data.get('agent')}")
            return True
        else:
            print(f"❌ Health check failed with status {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False


def test_categories():
    """Test /categories.json endpoint"""
    print("\n📚 Testing /categories.json...")
    try:
        r = requests.get(f"{BASE_URL}/categories.json", headers=HEADERS, timeout=30)
        if r.status_code == 200:
            data = r.json()
            count = data.get('count', 0)
            print(f"✅ Categories retrieved: {count} categories")
            if count > 0:
                print(f"   First 5: {data.get('categories', [])[:5]}")
            return True
        else:
            print(f"❌ Categories failed with status {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ Categories error: {e}")
        return False


def test_search(category="Travel"):
    """Test /search-json endpoint"""
    print(f"\n🔍 Testing /search-json with category '{category}'...")
    try:
        payload = {"product": category}
        r = requests.post(
            f"{BASE_URL}/search-json",
            headers=HEADERS,
            data=json.dumps(payload),
            timeout=60
        )
        if r.status_code == 200:
            data = r.json()
            status = data.get('status')
            items = data.get('items', [])
            print(f"✅ Search completed: status={status}, items={len(items)}")
            if items:
                print(f"   First item: {items[0].get('title')} - {items[0].get('price')}")
            return True
        else:
            print(f"❌ Search failed with status {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ Search error: {e}")
        return False


def test_run_goal(goal="list categories"):
    """Test /api/run endpoint"""
    print(f"\n🧠 Testing /api/run with goal '{goal}'...")
    try:
        payload = {"goal": goal, "planner": "builtin"}
        r = requests.post(
            f"{BASE_URL}/api/run",
            headers=HEADERS,
            data=json.dumps(payload),
            timeout=120
        )
        if r.status_code == 200:
            data = r.json()
            status = data.get('status')
            result = data.get('result', {})
            print(f"✅ Goal execution completed: status={status}")
            print(f"   Result status: {result.get('status')}")
            if result.get('categories'):
                print(f"   Categories found: {len(result.get('categories', []))}")
            return True
        else:
            print(f"❌ Goal execution failed with status {r.status_code}")
            print(f"   Response: {r.text}")
            return False
    except Exception as e:
        print(f"❌ Goal execution error: {e}")
        return False


def main():
    print("=" * 60)
    print("🤖 Robot Driver MCP Server Test Suite")
    print("=" * 60)

    results = []

    # Run all tests
    results.append(("Health Check", test_health()))
    results.append(("Categories", test_categories()))
    results.append(("Search", test_search("Travel")))
    results.append(("Run Goal", test_run_goal("list categories")))

    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    main()