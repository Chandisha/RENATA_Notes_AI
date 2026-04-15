import meeting_database as db
user = db.fetch_one("SELECT * FROM users WHERE email = 'chandishadas410@gmail.com'")
print(user)
