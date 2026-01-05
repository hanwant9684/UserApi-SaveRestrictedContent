"""
Telegram bot with minimal WSGI server (replaces Flask for ~15-20MB RAM savings)
Uses Python's built-in wsgiref - zero dependencies
Optimized for constrained environments (Render 512MB, Replit)
"""
import os
import sys
import secrets
import hashlib
import sqlite3
import json
import asyncio
import threading
import time
from urllib.parse import parse_qs
from html import escape
from http.cookies import SimpleCookie
from logger import LOGGER

# Initialize module logger
_logger = LOGGER(__name__)

def load_landing_page(session_id):
    """Landing page shown before ad verification - prevents premature code generation"""
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex, nofollow">
    <title>Complete Verification</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
        .container { background: white; border-radius: 20px; padding: 40px; max-width: 500px; width: 100%; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3); text-align: center; }
        .icon { font-size: 64px; margin-bottom: 20px; animation: scaleIn 0.5s ease-out; }
        @keyframes scaleIn { from { transform: scale(0); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        h1 { color: #2d3748; margin-bottom: 15px; font-size: 28px; }
        .message { color: #718096; margin-bottom: 30px; font-size: 16px; line-height: 1.6; }
        .instructions { background: #edf2f7; border-radius: 12px; padding: 20px; text-align: left; margin: 25px 0; }
        .instructions h3 { color: #2d3748; font-size: 18px; margin-bottom: 15px; }
        .instructions ol { color: #4a5568; padding-left: 20px; line-height: 1.8; }
        .btn { border: none; padding: 16px 40px; border-radius: 8px; font-size: 18px; font-weight: 600; cursor: pointer; margin: 10px 5px; transition: all 0.3s ease; display: inline-block; text-decoration: none; min-width: 250px; }
        .btn-primary { background: #48bb78; color: white; }
        .btn-primary:hover { background: #38a169; transform: translateY(-2px); box-shadow: 0 6px 20px rgba(72, 187, 120, 0.4); }
        @media (max-width: 500px) {
            .container { padding: 30px 20px; }
            h1 { font-size: 24px; }
            .btn { min-width: 100%; margin: 8px 0; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">🎯</div>
        <h1>Almost There!</h1>
        <p class="message">You've successfully completed the ad. Click the button below to get your verification code.</p>
        
        <div class="instructions">
            <h3>📋 What happens next?</h3>
            <ol>
                <li>Click "Get Verification Code" below</li>
                <li>Copy your unique code</li>
                <li>Go back to the Telegram bot</li>
                <li>Enter the code to unlock premium downloads</li>
            </ol>
        </div>
        
        <a href="/verify-ad?session={{SESSION_ID}}&confirm=1" class="btn btn-primary">✅ Get Verification Code</a>
    </div>
</body>
</html>'''.replace('{{SESSION_ID}}', escape(session_id))
    return html

def load_template(code, title, message, bot_username):
    """Minimal HTML template - replaces Jinja2"""
    icon = '✅' if code else '❌'
    
    auto_verify_html = ''
    if code:
        if bot_username:
            auto_verify_html = f'<a href="https://t.me/{escape(bot_username)}?start=verify_{escape(code)}" class="btn btn-primary" id="autoVerifyBtn">✅ Auto-Verify in Bot</a><p style="margin: 15px 0; color: #718096; font-size: 14px;">Recommended: One-click verification ☝️</p>'
        else:
            auto_verify_html = '<div class="alert alert-info show">ℹ️ Bot username not configured. Use manual verification below.</div>'
        
        code_section = f'''
    <div class="code-box" id="codeBox">
        <div class="code-label">Your Verification Code</div>
        <div class="verification-code" id="code" onclick="copyCode()" title="Click to copy">{escape(code)}</div>
    </div>
    <div class="timer-warning" id="timerWarning">
        ⏰ This code expires in <span id="timeRemaining">30:00</span> minutes
    </div>
    {auto_verify_html}
    <button class="btn btn-secondary" id="copyBtn" onclick="copyCode()">📋 Copy Code</button>
    <div class="instructions">
        <h3>📱 Manual Verification:</h3>
        <ol>
            <li>Go back to the Telegram bot</li>
            <li>Send this command:<br><code>/verifypremium {escape(code)}</code></li>
            <li>Enjoy your free downloads!</li>
        </ol>
    </div>
    '''
    else:
        code_section = f'''
    <div class="instructions">
        <h3>❓ What happened?</h3>
        <p style="margin-bottom: 15px;">{escape(message)}</p>
        <ol>
            <li>Go back to the Telegram bot</li>
            <li>Use <code>/getpremium</code> to get a new ad link</li>
            <li>Complete the ad verification</li>
            <li>You'll receive a valid code</li>
        </ol>
    </div>
    '''
    
    escaped_code = escape(code) if code else ''
    
    html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex, nofollow">
    <title>Verification {{STATUS}}</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }
        .container { background: white; border-radius: 20px; padding: 40px; max-width: 500px; width: 100%; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3); text-align: center; }
        .success-icon { font-size: 64px; margin-bottom: 20px; animation: scaleIn 0.5s ease-out; }
        @keyframes scaleIn { from { transform: scale(0); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        h1 { color: #2d3748; margin-bottom: 15px; font-size: 28px; }
        .message { color: #718096; margin-bottom: 30px; font-size: 16px; line-height: 1.6; }
        .code-box { background: #f7fafc; border: 2px dashed #667eea; border-radius: 12px; padding: 20px; margin: 25px 0; }
        .code-label { color: #4a5568; font-size: 14px; font-weight: 600; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 1px; }
        .verification-code { font-size: 32px; font-weight: bold; color: #667eea; font-family: 'Courier New', monospace; letter-spacing: 4px; user-select: all; cursor: pointer; padding: 10px; background: white; border-radius: 8px; transition: all 0.3s ease; }
        .verification-code:hover { background: #edf2f7; transform: scale(1.05); }
        .timer-warning { background: #fef5e7; border: 1px solid #f39c12; border-radius: 8px; padding: 12px; margin: 15px 0; color: #856404; font-size: 14px; }
        .instructions { background: #edf2f7; border-radius: 12px; padding: 20px; text-align: left; margin-top: 25px; }
        .instructions h3 { color: #2d3748; font-size: 18px; margin-bottom: 15px; }
        .instructions ol { color: #4a5568; padding-left: 20px; line-height: 1.8; }
        .instructions code { background: white; padding: 2px 8px; border-radius: 4px; font-family: 'Courier New', monospace; color: #667eea; font-size: 14px; }
        .btn { border: none; padding: 14px 32px; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; margin: 10px 5px; transition: all 0.3s ease; display: inline-block; text-decoration: none; min-width: 200px; }
        .btn-primary { background: #48bb78; color: white; }
        .btn-primary:hover { background: #38a169; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(72, 187, 120, 0.4); }
        .btn-secondary { background: #667eea; color: white; }
        .btn-secondary:hover { background: #5568d3; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4); }
        .btn.success { background: #48bb78; }
        .alert { padding: 12px 16px; border-radius: 8px; margin: 15px 0; font-size: 14px; }
        .alert-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        @media (max-width: 500px) {
            .container { padding: 30px 20px; }
            h1 { font-size: 24px; }
            .verification-code { font-size: 24px; letter-spacing: 2px; }
            .btn { min-width: 100%; margin: 8px 0; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="success-icon">{{ICON}}</div>
        <h1>{{TITLE}}</h1>
        <p class="message">{{MESSAGE}}</p>
        <div id="alertContainer"></div>
        {{CODE_SECTION}}
    </div>
    <script>
        const code = '{{ESCAPED_CODE}}';
        const hasCode = code && code !== '';
        function copyCode() {
            if (!code) return;
            const btn = document.getElementById('copyBtn');
            navigator.clipboard.writeText(code).then(() => {
                btn.textContent = '✓ Copied!';
                btn.classList.add('success');
                setTimeout(() => { btn.textContent = '📋 Copy Code'; btn.classList.remove('success'); }, 2000);
            }).catch(() => {
                const textArea = document.createElement('textarea');
                textArea.value = code;
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                btn.textContent = '✓ Copied!';
                setTimeout(() => { btn.textContent = '📋 Copy Code'; }, 2000);
            });
        }
        if (hasCode) {
            let expiryTime = new Date(Date.now() + 30 * 60 * 1000);
            setInterval(() => {
                const remaining = expiryTime - Date.now();
                if (remaining <= 0) { document.getElementById('timeRemaining').textContent = 'EXPIRED'; return; }
                const minutes = Math.floor(remaining / 60000);
                const seconds = Math.floor((remaining % 60000) / 1000);
                document.getElementById('timeRemaining').textContent = minutes + ':' + seconds.toString().padStart(2, '0');
            }, 1000);
        }
    </script>
</body>
</html>'''
    html = html.replace('{{STATUS}}', "Successful" if code else "Failed")
    html = html.replace('{{ICON}}', icon)
    html = html.replace('{{TITLE}}', escape(title))
    html = html.replace('{{MESSAGE}}', escape(message))
    html = html.replace('{{CODE_SECTION}}', code_section)
    html = html.replace('{{ESCAPED_CODE}}', escaped_code)
    
    return html

# Simple in-memory session store with expiry timestamps
_admin_sessions = {}
_SESSION_MAX_AGE = 86400  # 24 hours in seconds

def _cleanup_expired_sessions():
    """Remove expired admin sessions to prevent memory leak"""
    current_time = time.time()
    expired = [sid for sid, created_at in _admin_sessions.items() 
               if current_time - created_at > _SESSION_MAX_AGE]
    for sid in expired:
        del _admin_sessions[sid]

def check_admin_auth(environ):
    """Check if user is authenticated as admin via session cookie"""
    _cleanup_expired_sessions()
    cookie_header = environ.get('HTTP_COOKIE', '')
    if not cookie_header: return False
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    if 'admin_session' in cookie:
        session_id = cookie['admin_session'].value
        if session_id in _admin_sessions:
            created_at = _admin_sessions[session_id]
            if time.time() - created_at <= _SESSION_MAX_AGE:
                return True
            else:
                del _admin_sessions[session_id]
    return False

def create_admin_session():
    """Create a new admin session and return session ID"""
    _cleanup_expired_sessions()
    session_id = secrets.token_urlsafe(32)
    _admin_sessions[session_id] = time.time()
    return session_id

def verify_password(password):
    """Verify admin password"""
    admin_password = os.getenv('ADMIN_PASSWORD', '')
    return admin_password and password == admin_password

def application(environ, start_response):
    """Minimal WSGI application"""
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')
    
    headers_common = [
        ('Cache-Control', 'no-cache, no-store, must-revalidate'),
        ('Pragma', 'no-cache'),
        ('Expires', '0')
    ]
    
    try:
        if path == '/':
            status = '200 OK'
            body = b'{"status": "online", "message": "Telegram Bot is running!"}'
            headers = [('Content-Type', 'application/json; charset=utf-8')] + headers_common
            start_response(status, headers)
            return [body]
        
        elif path == '/health':
            status = '204 No Content'
            headers = headers_common
            start_response(status, headers)
            return [b'']
        
        elif path == '/verify-ad' and method == 'GET':
            from ad_monetization import ad_monetization
            from config import PyroConf
            query_string = environ.get('QUERY_STRING', '')
            params = parse_qs(query_string)
            session_id = params.get('session', [''])[0].strip()
            confirm = params.get('confirm', [''])[0].strip()
            
            if not session_id:
                html = load_template('', 'Invalid Request', 'No session ID provided.', PyroConf.BOT_USERNAME or '')
            elif confirm != '1':
                html = load_landing_page(session_id)
            else:
                success, code, message = ad_monetization.verify_ad_completion(session_id)
                if success:
                    html = load_template(code, 'Ad Completed Successfully! 🎉', 'Congratulations!', PyroConf.BOT_USERNAME or '')
                else:
                    html = load_template('', 'Verification Failed', message, PyroConf.BOT_USERNAME or '')
            
            status = '200 OK'
            body = html.encode('utf-8')
            headers = [('Content-Type', 'text/html; charset=utf-8')] + headers_common
            start_response(status, headers)
            return [body]
        
        elif path == '/admin/login' and method == 'GET':
            html = '''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Admin Login</title></head>
<body><div class="container"><h1>🔐 Admin Login</h1>
<form method="POST" action="/admin/login">
<input type="password" name="password" required autofocus><button type="submit">Login</button>
</form></div></body></html>'''
            status = '200 OK'
            body = html.encode('utf-8')
            headers = [('Content-Type', 'text/html; charset=utf-8')] + headers_common
            start_response(status, headers)
            return [body]
        
        elif path == '/admin/login' and method == 'POST':
            content_length = int(environ.get('CONTENT_LENGTH', 0))
            request_body = environ['wsgi.input'].read(content_length).decode('utf-8')
            params = parse_qs(request_body)
            password = params.get('password', [''])[0]
            if verify_password(password):
                session_id = create_admin_session()
                status = '303 See Other'
                headers = [('Location', '/files'), ('Set-Cookie', f'admin_session={session_id}; Path=/; HttpOnly; Max-Age=86400')] + headers_common
                start_response(status, headers)
                return [b'']
            else:
                status = '401 Unauthorized'
                start_response(status, headers_common)
                return [b'Invalid Password']

        elif path == '/files' and method == 'GET':
            if not check_admin_auth(environ):
                status = '303 See Other'
                headers = [('Location', '/admin/login')] + headers_common
                start_response(status, headers)
                return [b'']
            
            files_list = []
            for root, dirs, files in os.walk(os.getcwd()):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'node_modules', '.git']]
                for filename in files:
                    if filename.startswith('.'): continue
                    filepath = os.path.join(root, filename)
                    rel_path = os.path.relpath(filepath, os.getcwd())
                    stat = os.stat(filepath)
                    files_list.append({'name': rel_path, 'size': stat.st_size})
            
            files_html = ''.join([f'<tr><td>{f["name"]}</td><td>{f["size"]}</td><td><a href="/download?file={f["name"]}">Download</a></td></tr>' for f in files_list])
            html = f'<html><body><h1>Files</h1><table>{files_html}</table><a href="/admin/login">Logout</a></body></html>'
            status = '200 OK'
            body = html.encode('utf-8')
            headers = [('Content-Type', 'text/html; charset=utf-8')] + headers_common
            start_response(status, headers)
            return [body]

        elif path == '/database/execute' and method == 'POST':
            if not check_admin_auth(environ):
                status = '401 Unauthorized'
                start_response(status, headers_common)
                return [b'Unauthorized']
            try:
                content_length = int(environ.get('CONTENT_LENGTH', 0))
                request_body = environ['wsgi.input'].read(content_length).decode('utf-8')
                params = parse_qs(request_body)
                query = params.get('query', [''])[0].strip()
                conn = sqlite3.connect('telegram_bot.db')
                cursor = conn.cursor()
                cursor.execute(query)
                if query.lower().startswith('select'):
                    rows = cursor.fetchall()
                    body = json.dumps({'success': True, 'rows': rows}).encode('utf-8')
                else:
                    conn.commit()
                    body = json.dumps({'success': True, 'affected': conn.total_changes}).encode('utf-8')
                conn.close()
                status = '200 OK'
                headers = [('Content-Type', 'application/json')] + headers_common
                start_response(status, headers)
                return [body]
            except Exception as e:
                status = '200 OK'
                body = json.dumps({'success': False, 'error': str(e)}).encode('utf-8')
                start_response(status, [('Content-Type', 'application/json')] + headers_common)
                return [body]

        else:
            status = '404 Not Found'
            start_response(status, headers_common)
            return [b'Not Found']

    except Exception as e:
        status = '500 Internal Server Error'
        start_response(status, headers_common)
        return [str(e).encode('utf-8')]


def run_bot():
    """Run the Telegram bot in a background thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    import main
    async def start_bot():
        try:
            await main.bot.start(bot_token=main.PyroConf.BOT_TOKEN)
            main.LOGGER(__name__).info("Bot started successfully")
            await main.bot.run_until_disconnected()
        finally:
            await main.bot.disconnect()
    loop.run_until_complete(start_bot())

bot_started = False
def start_bot_once():
    global bot_started
    if not bot_started:
        threading.Thread(target=run_bot, daemon=True).start()
        bot_started = True

start_bot_once()

if __name__ == '__main__':
    from waitress import serve
    port = int(os.environ.get('PORT', 5000))
    _logger.info(f"Starting Waitress WSGI server on 0.0.0.0:{port}")
    serve(application, host='0.0.0.0', port=port, threads=4)
