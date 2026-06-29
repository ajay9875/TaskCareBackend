# TaskCare360 Mobile App 🚀
A full-stack Todo application built with **React Native (Expo)** and **Flask (SQLAlchemy)**.

## 📁 Project Structure
- **/TaskCareBackend**: Flask REST API, SQLite/MySQL database, and OTP-based authentication.
- **/TaskCareMobile**: React Native frontend using Expo Router and Context API.

## 🛠️ Tech Stack
- **Frontend:** React Native, Expo, Lucide Icons.
- **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-CORS.
- **Database:** PostgreSQL (Dev) / MySQL (Production).
- **Auth:** Email OTP Verification (SMTP) & Session Management.

## ⚙️ Setup Instructions

### Backend (Flask)
1. Navigate to `TaskCareBackend`.
2. Activate venv: `source venv/Scripts/activate` (Windows).
3. Install dependencies: `pip install -r requirements.txt`.
4. Run server: `python app.py`.

### Mobile (React Native)
1. Navigate to `TaskCareMobile`.
2. Install dependencies: `npm install`.
3. Start Expo: `npx expo start`.
4. Press `a` for Android Emulator.

## 🔗 Connection Tip
Ensure your mobile app connects via `http://10.0.2.2:5000` for Android Emulator or your Laptop IP for physical devices. Run `adb reverse tcp:5000 tcp:5000` to bridge the connection.

# After updating and commiting with git run this command to fetch newly commit changes at deployment server
(flask_env) 19:25 ~/flask_mobile (main)$ git fetch origin
remote: Enumerating objects: 8, done.
remote: Counting objects: 100% (8/8), done.
remote: Compressing objects: 100% (1/1), done.
remote: Total 6 (delta 5), reused 6 (delta 5), pack-reused 0 (from 0)
Unpacking objects: 100% (6/6), 578 bytes | 4.00 KiB/s, done.
From https://github.com/ajay9875/TaskCareBackend
   c676074..c82c59b  main       -> origin/main
(flask_env) 19:25 ~/flask_mobile (main)$ git reset --hard origin/main
HEAD is now at c82c59b Fix:deleted logic to send email via schedular function and used uptimerobot to send via send-daily-eamil function
(flask_env) 19:26 ~/flask_mobile (main)$ 