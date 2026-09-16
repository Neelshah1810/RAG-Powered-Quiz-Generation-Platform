"""Quick test script to verify all endpoints work."""
import requests

BASE = "http://localhost:8000/api"

# 1. Login
print("=== Testing Login ===")
r = requests.post(f"{BASE}/auth/login", json={"email": "admin@academix.ai", "password": "password123"})
print(f"Login: {r.status_code}")
if r.status_code != 200:
    print(f"Login failed: {r.text}")
    exit(1)

token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 2. Test Courses
print("\n=== Testing Courses ===")
r = requests.get(f"{BASE}/courses/", headers=headers)
print(f"List courses: {r.status_code}")

# 3. Test Create Course
r = requests.post(f"{BASE}/courses/", headers=headers, json={
    "name": "Test Course", "code": "TEST101", "semester": 8
})
print(f"Create course: {r.status_code}")
if r.status_code == 200:
    print(f"  Created: {r.json().get('name')}")

# 4. Test Scheduler - List Events
print("\n=== Testing Scheduler ===")
r = requests.get(f"{BASE}/scheduler/events", headers=headers)
print(f"List events: {r.status_code}")

# 5. Test Scheduler - Create Event
r = requests.post(f"{BASE}/scheduler/events", headers=headers, json={
    "title": "Test Lecture",
    "event_type": "lecture",
    "start_at": "2026-09-05T10:00:00Z",
    "end_at": "2026-09-05T11:00:00Z",
    "description": "Test lecture event",
})
print(f"Create event: {r.status_code}")
if r.status_code == 200:
    print(f"  Created: {r.json().get('title')}")
elif r.status_code != 200:
    print(f"  Error: {r.text}")

# 6. Test Notices - List
print("\n=== Testing Notices ===")
r = requests.get(f"{BASE}/notices/", headers=headers)
print(f"List notices: {r.status_code}")

# 7. Test Notices - Create
r = requests.post(f"{BASE}/notices/", headers=headers, json={
    "title": "Test Announcement",
    "body": "This is a test announcement from the admin.",
    "notice_type": "announcement",
})
print(f"Create notice: {r.status_code}")
if r.status_code == 200:
    print(f"  Created: {r.json().get('title')}")
elif r.status_code != 200:
    print(f"  Error: {r.text}")

# 8. Test Staff List
print("\n=== Testing Staff List ===")
r = requests.get(f"{BASE}/users/staff", headers=headers)
print(f"Staff list: {r.status_code}")
if r.status_code == 200:
    staff = r.json()
    print(f"  Found {len(staff)} staff members")
    for s in staff:
        print(f"    - {s.get('full_name')} ({s.get('role')})")

# 9. Test with student account
print("\n=== Testing Student Login ===")
r = requests.post(f"{BASE}/auth/login", json={"email": "student@academix.ai", "password": "password123"})
print(f"Student login: {r.status_code}")
if r.status_code == 200:
    stu_token = r.json()["access_token"]
    stu_headers = {"Authorization": f"Bearer {stu_token}"}
    
    # Student can see events
    r = requests.get(f"{BASE}/scheduler/events", headers=stu_headers)
    print(f"Student list events: {r.status_code}")
    if r.status_code == 200:
        print(f"  Student sees {len(r.json())} events")
    
    # Student can see notices
    r = requests.get(f"{BASE}/notices/", headers=stu_headers)
    print(f"Student list notices: {r.status_code}")
    if r.status_code == 200:
        print(f"  Student sees {r.json().get('total')} notices")
    
    # Student can create meeting
    r = requests.post(f"{BASE}/scheduler/events", headers=stu_headers, json={
        "title": "Meeting with teacher",
        "event_type": "meeting",
        "start_at": "2026-09-06T14:00:00Z",
        "end_at": "2026-09-06T15:00:00Z",
    })
    print(f"Student create meeting: {r.status_code}")
    
    # Student CANNOT create lecture
    r = requests.post(f"{BASE}/scheduler/events", headers=stu_headers, json={
        "title": "Unauthorized Lecture",
        "event_type": "lecture",
        "start_at": "2026-09-06T14:00:00Z",
        "end_at": "2026-09-06T15:00:00Z",
    })
    print(f"Student create lecture (should fail): {r.status_code} (expected 403)")

print("\n=== All tests complete ===")
