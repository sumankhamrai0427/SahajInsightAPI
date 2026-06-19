# import os
# import smtplib
# from email.mime.text import MIMEText
# from flask import request, jsonify
# from dotenv import load_dotenv

# # Load .env variables
# load_dotenv()

# # Read from environment
# GMAIL_USER = os.getenv("GMAIL_USER")
# GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
# RECEIVER_EMAILS = os.getenv("RECEIVER_EMAIL").split(",")


# def send_email(name, user_email, subject, message_body):
#     """Sends an email using Gmail SMTP."""
#     msg_content = (
#         f"Name: {name}\n"
#         f"Email: {user_email}\n"
#         f"Subject: {subject}\n\n"
#         f"Message:\n{message_body}"
#     )

#     msg = MIMEText(msg_content)
#     msg["Subject"] = f"New Contact Form: {subject}"
#     msg["From"] = GMAIL_USER
#     msg["To"] = ", ".join(RECEIVER_EMAILS)

#     try:
#         with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
#             server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
#             server.send_message(
#                 msg,
#                 from_addr=GMAIL_USER,
#                 to_addrs=RECEIVER_EMAILS
#             )
#         return True

#     except Exception as e:
#         print(" Error sending email:", e)
#         return False


# def handle_contact_controller():
#     data = request.get_json() or {}

#     name = data.get("name")
#     email = data.get("email")
#     subject = data.get("subject")
#     message = data.get("message")

#     # Validation
#     if not all([name, email, subject]):
#         return jsonify({
#             "success": False,
#             "message": "name, email, subject and message are required"
#         }), 400
    
#     if not message:
#         message = "No message provided (Pricing enquiry form)"

#     # Send email
#     if send_email(name, email, subject, message):
#         return jsonify({
#             "success": True,
#             "message": "Email sent successfully"
#         }), 200

#     return jsonify({
#         "success": False,
#         "message": "Failed to send email"
#     }), 500

import os
import smtplib
from email.mime.text import MIMEText
from flask import request, jsonify
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

# Read from environment (DOMAIN EMAIL)
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
RECEIVER_EMAILS = os.getenv("RECEIVER_EMAIL").split(",")


def send_email(name, user_email, subject, message_body):
    """Sends an email using SahajInsight domain SMTP (cPanel)."""

    msg_content = (
        f"Name: {name}\n"
        f"Email: {user_email}\n\n"
        f"Message:\n{message_body}"
    )

    msg = MIMEText(msg_content)
    msg["Subject"] = f"Immediate {subject} from Sahajinsight"
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(RECEIVER_EMAILS)
    msg["Reply-To"] = user_email

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            # print("LOGIN SUCCESS")

            server.send_message(
                msg,
                from_addr=SMTP_USER,
                to_addrs=RECEIVER_EMAILS
            )
        # with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        #     server.starttls()
        #     server.login(SMTP_USER, SMTP_PASSWORD)
        #     server.send_message(msg)
        return True

    except Exception as e:
        print("SMTP Error:", e)
        return False


def handle_contact_controller():
    data = request.get_json() or {}

    name = data.get("name")
    email = data.get("email")
    subject = data.get("subject")
    message = data.get("message")

    # Validation
    if not all([name, email, subject]):
        return jsonify({
            "success": False,
            "message": "name, email and subject are required"
        }), 400

    if not message:
        message = "No message provided (Pricing enquiry form)"

    # Send email
    if send_email(name, email, subject, message):
        return jsonify({
            "success": True,
            "message": "Email sent successfully"
        }), 200

    return jsonify({
        "success": False,
        "message": "Failed to send email"
    }), 500
