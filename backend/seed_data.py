"""
Academix AI — Seed Demo Users Script
"""

import sys
import os
import asyncio

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.database import get_supabase_admin

DEMO_USERS = [
    {
        "email": "admin@academix.ai",
        "password": "password123",
        "full_name": "Dr. Sarah Jenkins (Admin)",
        "role": "admin",
        "department": "Computer Science",
    },
    {
        "email": "teacher@academix.ai",
        "password": "password123",
        "full_name": "Prof. Alan Turing",
        "role": "teacher",
        "department": "Computer Science",
    },
    {
        "email": "student@academix.ai",
        "password": "password123",
        "full_name": "Alex Johnson",
        "role": "student",
        "department": "Computer Science",
    },
]

async def main():
    supabase = get_supabase_admin()
    print("Ensuring Demo Accounts & Profiles exist in Supabase...\n")

    for u in DEMO_USERS:
        email = u["email"]
        try:
            # Check or create auth user
            user_id = None
            res = supabase.table("profiles").select("id").eq("email", email).execute()
            if res.data and len(res.data) > 0:
                user_id = res.data[0]["id"]
            else:
                try:
                    auth_res = supabase.auth.admin.create_user({
                        "email": email,
                        "password": u["password"],
                        "email_confirm": True,
                        "user_metadata": {
                            "full_name": u["full_name"],
                            "role": u["role"],
                        },
                    })
                    user_id = auth_res.user.id
                except Exception as ex:
                    # If auth user exists but profile missing
                    users = supabase.auth.admin.list_users()
                    for usr in users:
                        if usr.email == email:
                            user_id = usr.id
                            break

            if user_id:
                # Upsert profile row
                supabase.table("profiles").upsert({
                    "id": str(user_id),
                    "email": email,
                    "full_name": u["full_name"],
                    "role": u["role"],
                    "department": u["department"],
                }).execute()
                print(f"  [SUCCESS] Synced profile for: {email} ({u['role']})")
        except Exception as e:
            print(f"  [ERROR] {email}: {e}")

    print("\nComplete! Try logging in again.")

if __name__ == "__main__":
    asyncio.run(main())
