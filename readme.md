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