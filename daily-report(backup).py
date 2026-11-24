# Daily email report for the steps
def send_daily_progress_report():
    sender_email = (os.getenv('EMAIL_USER') or '').replace(' ', '')
    sender_password = (os.getenv('EMAIL_PASS') or '').replace(' ', '')
    login_url = "https://TaskCare360.pythonanywhere.com/open-app"

    # 📋 Tracking lists for the report
    sent_to = []
    skipped = []
    failed = []

    if not sender_email or not sender_password:
        print("❌ Email credentials missing")
        return {
            "error": "Email credentials missing",
            "total_users": 0,
            "emails_sent": 0,
            "sent_to": sent_to,
            "skipped": skipped,
            "failed": failed,
        }

    try:
        users = User.query.all()
        if not users:
            print("No users found")
            return {
                "error": "No users found",
                "total_users": 0,
                "emails_sent": 0,
                "sent_to": sent_to,
                "skipped": skipped,
                "failed": failed,
            }

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)

            for user in users:
                try:
                    # --- GET TODAY'S DATE PROPERLY ---
                    today = datetime.now(IST).date()

                    # Query StepLog for today
                    today_stats = StepLog.query.filter_by(
                        user_id=user.id,
                        date=today
                    ).first()

                    # 🏃‍♂️ Extract separated tracking data variables securely
                    walk_steps = today_stats.walking_steps if today_stats else 0
                    tread_steps = today_stats.treadmill_steps if today_stats else 0

                    # Pull tasks early to determine if we should skip the email entirely
                    tasks = Todo.query.filter_by(user_id=user.id, is_completed=False, is_deleted=False).order_by(Todo.SNo.desc()).all()
                    
                    # 🛑 TOTAL EMPTY DETECTION:
                    # If they have NO steps AND NO pending tasks, send a friendly nudge email instead of skipping.
                    is_empty_user = (walk_steps == 0 and tread_steps == 0 and not tasks)
                    if is_empty_user:
                        print(f"📨 Nudge email for {user.name} ({user.email}): No steps and no pending tasks.")

                    # 📊 CASE 1: User HAS step data today -> Render full premium report card
                    if walk_steps > 0 or tread_steps > 0:
                        walk_km = round(walk_steps * 0.000762, 2)
                        walk_cal = int(walk_steps * 0.04)

                        tread_km = round(tread_steps * 0.000762, 2)
                        tread_cal = int(tread_steps * 0.05)

                        combined_steps = walk_steps + tread_steps
                        combined_km = round(combined_steps * 0.000762, 2)
                        combined_cal = walk_cal + tread_cal

                        target = user.target_steps if user.target_steps else 5000
                        steps_left = max(0, target - combined_steps)
                        progress_percent = min(int((combined_steps / target) * 100), 100) if target > 0 else 0

                        fitness_html = f"""
                        <div style="background-color: #16213e; padding: 24px; border-radius: 22px; border: 1.5px solid rgba(255, 255, 255, 0.12); max-width: 460px; margin: 0 auto 20px auto; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; box-shadow: 0 10px 25px rgba(0,0,0,0.35); color: #ffffff;">
                            <div style="font-size: 16px; color: #ffffff; font-weight: 800; margin-bottom: 20px; letter-spacing: 0.3px;">
                                📆 {today.strftime('%d %b')} Report
                            </div>
                            <table style="width: 100%; border-collapse: collapse; margin-bottom: 4px;" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="width: 48%; vertical-align: top;">
                                        <div style="margin-bottom: 12px; padding-left: 4px;">
                                            <span style="color: #4ecca3; font-size: 13px; font-weight: 800; letter-spacing: 0.8px;">🚶 WALKING</span>
                                        </div>
                                        <div style="background-color: rgba(255, 255, 255, 0.04); padding: 16px 14px; border-radius: 14px; border: 1px solid rgba(255, 255, 255, 0.08); min-height: 150px;">
                                            <div style="font-size: 19px; font-weight: bold; color: #ffffff; margin-top: 2px;">{walk_steps:,}</div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 12px;">STEPS</div>
                                            <div style="font-size: 19px; font-weight: bold; color: #ffffff; margin-top: 2px;">{walk_km:.2f} <span style="font-size: 11px; color: #a4b0be; font-weight: 500;">KM</span></div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 12px;">DISTANCE</div>
                                            <div style="font-size: 19px; font-weight: bold; color: #ff6b35; margin-top: 2px;">{walk_cal} <span style="font-size: 11px; color: #a4b0be; font-weight: 500;">CAL</span></div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;">ENERGY</div>
                                        </div>
                                    </td>
                                    <td style="width: 4%;"></td>
                                    <td style="width: 48%; vertical-align: top;">
                                        <div style="margin-bottom: 12px; padding-left: 4px;">
                                            <span style="color: #4ecca3; font-size: 13px; font-weight: 800; letter-spacing: 0.8px;">⚡ TREADMILL</span>
                                        </div>
                                        <div style="background-color: rgba(255, 255, 255, 0.04); padding: 16px 14px; border-radius: 14px; border: 1px solid rgba(255, 255, 255, 0.08); min-height: 150px;">
                                            <div style="font-size: 19px; font-weight: bold; color: #ffffff; margin-top: 2px;">{tread_steps:,}</div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 12px;">STEPS</div>
                                            <div style="font-size: 19px; font-weight: bold; color: #ffffff; margin-top: 2px;">{tread_km:.2f} <span style="font-size: 11px; color: #a4b0be; font-weight: 500;">KM</span></div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 12px;">DISTANCE</div>
                                            <div style="font-size: 19px; font-weight: bold; color: #ff6b35; margin-top: 2px;">{tread_cal} <span style="font-size: 11px; color: #a4b0be; font-weight: 500;">CAL</span></div>
                                            <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.5px;">ENERGY</div>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                            <div style="height: 1.5px; background-color: rgba(255, 255, 255, 0.15); margin: 24px 0 16px 0;"></div>
                            <h4 style="color: #4ecca3; font-size: 13px; font-weight: 800; letter-spacing: 1.2px; margin: 0 0 16px 0; text-align: left;">COMBINED PERFORMANCE</h4>
                            <table style="width: 100%; border-collapse: collapse;" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="width: 55%; vertical-align: middle;">
                                        <table style="width: 100%; border-collapse: collapse;">
                                            <tr>
                                                <td style="padding-bottom: 14px;">
                                                    <div style="font-size: 20px; font-weight: 800; color: #ffffff; line-height: 24px;">{combined_steps:,}</div>
                                                    <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.6px; margin-top: 2px;">TOTAL STEPS</div>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="padding-bottom: 14px;">
                                                    {f'<div style="font-size: 20px; font-weight: 800; color: #4ecca3; line-height: 24px;">{steps_left:,}</div>' if steps_left == 0 else f'<div style="font-size: 20px; font-weight: 800; color: #ffffff; line-height: 24px;">{steps_left:,}</div>'}
                                                    <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.6px; margin-top: 2px;">STEPS REMAINING</div>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td>
                                                    <div style="font-size: 20px; font-weight: 800; color: #ffffff; line-height: 24px;">{target:,}</div>
                                                    <div style="color: #a4b0be; font-size: 10px; font-weight: 700; letter-spacing: 0.6px; margin-top: 2px;">DAILY GOAL</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td style="width: 45%; vertical-align: middle; text-align: center; padding-left: 12px;">
                                        <div style="display: inline-block; padding: 12px 20px; background-color: rgba(255, 255, 255, 0.05); border-radius: 30px; border: 2px solid #4ecca3; margin-bottom: 12px;">
                                            <strong style="color: #ffffff; font-size: 18px; font-weight: 800;">{progress_percent}%</strong>
                                        </div>
                                        <div style="width: 70%; height: 1px; background-color: rgba(255, 255, 255, 0.15); margin: 0 auto 12px auto;"></div>
                                        <div style="text-align: center;">
                                            <div style="color: #ffffff; font-size: 18px; font-weight: 700; margin-bottom: 4px; line-height: 20px;">
                                                {combined_km:.2f} <span style="color: #a4b0be; font-size: 14px; font-weight: 600;">KM</span>
                                            </div>
                                            <div style="color: #ff6b35; font-size: 18px; font-weight: 700; line-height: 20px;">
                                                {combined_cal} <span style="color: #a4b0be; font-size: 14px; font-weight: 600;">CAL</span>
                                            </div>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                            <div style="background-color: rgba(255, 255, 255, 0.1); border-radius: 10px; height: 8px; overflow: hidden; margin: 24px 0 14px 0;">
                                <div style="background-color: #4ecca3; width: {progress_percent}%; height: 8px; border-radius: 10px;"></div>
                            </div>
                            <div style="text-align: center; margin-top: 28px;">
                                <a href="{login_url}" style="background-color: #4ecca3; color: #1a1a2e; padding: 14px 36px; text-decoration: none; border-radius: 12px; font-size: 15px; font-weight: bold; display: inline-block; box-shadow: 0 4px 12px rgba(78, 204, 163, 0.3); letter-spacing: 0.3px;">
                                    Open FitWisely
                                </a>
                            </div>
                        </div>
                        """
                    elif is_empty_user:
                        # 👋 CASE 3: User HAS NO steps AND NO tasks -> Friendly nudge email
                        fitness_html = f"""
                        <div style="background-color: #16213e; padding: 28px 24px; border-radius: 22px; border: 1.5px solid rgba(255, 255, 255, 0.12); max-width: 460px; margin: 0 auto 20px auto; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; box-shadow: 0 10px 25px rgba(0,0,0,0.35); color: #ffffff; text-align: center;">
                            <div style="font-size: 42px; margin-bottom: 10px;">👋</div>
                            <h3 style="color: #ffffff; font-size: 19px; font-weight: 800; margin: 0 0 10px 0; letter-spacing: 0.2px;">
                                Hi {user.name}, let's get started today!
                            </h3>
                            <p style="color: #a4b0be; font-size: 14px; line-height: 21px; margin: 0 0 18px 0;">
                                You haven't logged any activity or tasks yet today. Open the app to:
                            </p>
                            <div style="text-align: left; display: inline-block; margin: 0 auto 20px auto;">
                                <p style="color: #ffffff; font-size: 14px; margin: 0 0 10px 0;">
                                    📝 <strong>Add a task</strong> to stay productive
                                </p>
                                <p style="color: #ffffff; font-size: 14px; margin: 0 0 10px 0;">
                                    🚶 <strong>Walk</strong> to save your steps
                                </p>
                                <p style="color: #ffffff; font-size: 14px; margin: 0;">
                                    🎯 <strong>Hit your daily goal</strong> of {(user.target_steps if user.target_steps else 5000):,} steps
                                </p>
                            </div>
                            <div style="text-align: center; margin-top: 10px;">
                                <a href="{login_url}" style="background-color: #4ecca3; color: #1a1a2e; padding: 14px 36px; text-decoration: none; border-radius: 12px; font-size: 15px; font-weight: bold; display: inline-block; box-shadow: 0 4px 12px rgba(78, 204, 163, 0.3); letter-spacing: 0.3px;">
                                    Open FitWisely
                                </a>
                            </div>
                        </div>
                        """
                    else:
                        # 🚫 CASE 2: User HAS NO step data today -> Render the premium dashed empty block placeholder
                        fitness_html = f"""
                        <div style="background-color: #16213e; padding: 24px; border-radius: 22px; border: 1.5px dashed rgba(255, 255, 255, 0.15); max-width: 460px; margin: 0 auto 20px auto; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; text-align: center; color: #a4b0be;">
                            <div style="font-size: 16px; color: #ffffff; font-weight: 800; margin-bottom: 14px; text-align: left;">
                                📆 {today.strftime('%d %b')} Report
                            </div>
                            <p style="font-size: 14px; color: rgba(255,255,255,0.4); margin: 20px 0;">
                                💤 No fitness tracking activity or step records logged for today yet.
                            </p>
                            <div style="text-align: center; margin-top: 14px;">
                                <a href="{login_url}" style="background-color: rgba(255,255,255,0.08); color: #ffffff; padding: 10px 24px; text-decoration: none; border-radius: 10px; font-size: 13px; font-weight: bold; display: inline-block; border: 1px solid rgba(255,255,255,0.15);">
                                    Sync Steps Now
                                </a>
                            </div>
                        </div>
                        """

                    # Tasks section rendering framework
                    if is_empty_user:
                        # Nudge emails already show the CTA card above — no separate task box needed
                        task_content = ""
                    elif not tasks:
                        task_content = """
                        <div style="text-align: center; padding: 20px; border: 1px dashed #ddd; border-radius: 8px; font-family: Arial, sans-serif;">
                            🎉 Great job! No pending tasks. Keep it up!
                        </div>
                        """
                    else:
                        task_rows = ""
                        for task in tasks:
                            task_rows += f"""
                            <tr>
                                <td style="border:1px solid #ddd;padding:8px;">{task.title}</td>
                                <td style="border:1px solid #ddd;padding:8px;">{task.desc or 'No description'}</td>
                                <td style="border:1px solid #ddd;padding:8px;">{task.date_created.strftime('%Y-%m-%d')}</td>
                            </tr>
                            """

                        task_content = f"""
                        <h3 style="color: #333; font-family: Arial, sans-serif;">📋 Pending Tasks</h3>
                        <table style="border-collapse: collapse; width: 100%; font-family: Arial, sans-serif;">
                            <thead>
                                <tr style="background-color: #f2f2f2;">
                                    <th style="border:1px solid #ddd;padding:8px;text-align:left;">Title</th>
                                    <th style="border:1px solid #ddd;padding:8px;text-align:left;">Description</th>
                                    <th style="border:1px solid #ddd;padding:8px;text-align:left;">Date</th>
                                </tr>
                            </thead>
                            <tbody>{task_rows}</tbody>
                        </table>
                        <p style="font-family: Arial, sans-serif;"><strong>Total pending tasks:</strong> {len(tasks)}</p>
                        """

                    # Final HTML Assembly
                    html_body = f"""
                    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; color: #333;">
                        <h2>Hello, {user.name}! 👋</h2>
                        <p>Here's your daily progress report:</p>

                        {fitness_html}

                        {task_content}

                        <hr style="margin: 30px 0;">
                        <p style="font-size: 12px; color: #888; text-align: center;">
                            FitWisely — Your health & productivity partner 🚀
                        </p>
                    </div>
                    """

                    # Subject line varies for nudge emails
                    if is_empty_user:
                        subject = f"👋 Let's get started today - {today.strftime('%b %d')}"
                    else:
                        subject = f"📊 Daily Progress - {today.strftime('%b %d')}"

                    # Send email out to active user mailbox
                    msg = MIMEMultipart("alternative")
                    msg['From'] = f"FitWisely Progress <{sender_email}>"
                    msg['To'] = user.email
                    msg['Subject'] = subject
                    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

                    server.send_message(msg)
                    sent_to.append({
                        "email": user.email,
                        "name": user.name,
                        "type": "nudge" if is_empty_user else "report",
                    })
                    print(f"✅ Email sent to {user.email} ({'nudge' if is_empty_user else 'report'})")

                except Exception as e:
                    print(f"❌ Failed to send to {user.email}: {str(e)}")
                    failed.append({"email": user.email, "error": str(e)})
                    continue

            print(
                f"📧 Done — sent: {len(sent_to)} | skipped: {len(skipped)} "
                f"| failed: {len(failed)} | total users: {len(users)}"
            )
            return {
                "error": None,
                "total_users": len(users),
                "emails_sent": len(sent_to),
                "sent_to": sent_to,
                "skipped": skipped,
                "failed": failed,
            }

    except Exception as e:
        print(f"❌ Fatal error in send_daily_task_reminders: {str(e)}")
        return {
            "error": str(e),
            "total_users": 0,
            "emails_sent": 0,
            "sent_to": sent_to,
            "skipped": skipped,
            "failed": failed,
        }