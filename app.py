# ==============================================================================
# 1. 라이브러리 및 모듈 임포트
# ==============================================================================
import os                                  # 서버 환경변수(LINE API 키 등) 로드용
import re                                  # 정규표현식 명령어 파싱용 (/ㅁㄷㅅ [숫자])
import sqlite3                             # DB 연동 및 카운트/글자 수 집계용
from datetime import datetime              # 최근 활동 시간(last_active) 기록용
from flask import Flask, request, abort   # 웹 서버 구축 및 라인 웹훅 수신용

# LINE SDK v3 모듈
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    ImageMessage,
    StickerMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from apscheduler.schedulers.background import BackgroundScheduler  # 자정 리셋 스케줄러

# ==============================================================================
# 2. Flask 서버 및 LINE API 설정
# ==============================================================================
app = Flask(__name__)  # Flask 웹 서버 객체 생성

# Render 환경변수에서 라인 키 값 로드
CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ==============================================================================
# 3. 데이터베이스 및 스케줄러 설정
# ==============================================================================
def init_db():
    conn = sqlite3.connect('chat_stats.db')
    cursor = conn.cursor()
    # 유저별 누적 횟수(msg_count) 및 누적 글자 수(talk_length) 관리
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id TEXT PRIMARY KEY,
            nickname TEXT,
            msg_count INTEGER DEFAULT 0,
            talk_length INTEGER DEFAULT 0,
            last_active DATETIME
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def update_user_activity(user_id, nickname, text_len):
    """메시지 수신 시 카운트 +1 및 누적 글자 수(talk_length) ++"""
    conn = sqlite3.connect('chat_stats.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO user_stats (user_id, nickname, msg_count, talk_length, last_active)
        VALUES (?, ?, 1, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            nickname = excluded.nickname,
            msg_count = user_stats.msg_count + 1,
            talk_length = user_stats.talk_length + excluded.talk_length,
            last_active = excluded.last_active
    ''', (user_id, nickname, text_len, datetime.now()))
    
    conn.commit()
    conn.close()

def get_ranked_users(limit=5, order="DESC"):
    """상위/하위 N명 순위 및 메시지 수, 총 글자 수 조회"""
    conn = sqlite3.connect('chat_stats.db')
    cursor = conn.cursor()
    
    cursor.execute(f'''
        SELECT nickname, msg_count, talk_length 
        FROM user_stats 
        ORDER BY msg_count {order} 
        LIMIT ?
    ''', (limit,))
    
    results = cursor.fetchall()
    conn.close()
    return results

def clear_db():
    """매일 자정(00:00 KST)에 유저 통계 초기화"""
    conn = sqlite3.connect('chat_stats.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM user_stats')
    conn.commit()
    conn.close()
    print("🧹 [자정 정제 완료] user_stats 테이블이 초기화되었습니다.")

# 한국 시간(Asia/Seoul) 기준 매일 자정 00:00 리셋 스케줄러 실행
scheduler = BackgroundScheduler(daemon=True, timezone="Asia/Seoul")
scheduler.add_job(clear_db, 'cron', hour=0, minute=0)
scheduler.start()

# ==============================================================================
# 4. LINE 웹훅 수신 경로 (/callback)
# ==============================================================================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ==============================================================================
# 5. 메시지 이벤트 통합 처리
# ==============================================================================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    user_id = event.source.user_id
    reply_messages = []

    # 1. 메시지를 보낸 유저의 프로필(닉네임) 스캔
    user_nickname = "사용자"
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            if event.source.type == "group":
                try:
                    profile = line_bot_api.get_group_member_profile(event.source.group_id, user_id)
                    user_nickname = profile.display_name
                except Exception:
                    profile = line_bot_api.get_profile(user_id)
                    user_nickname = profile.display_name
            else:
                profile = line_bot_api.get_profile(user_id)
                user_nickname = profile.display_name
    except Exception as e:
        print(f"프로필 스캔 실패: {e}")

    # 2. 누구나 말하면 DB에 닉네임 저장, 카운트+1, 입력한 글자 수 누적(+=)
    current_text_len = len(user_text)
    update_user_activity(user_id, user_nickname, current_text_len)

    # --------------------------------------------------
    # 3. 키워드 응답 및 명령어 처리
    # --------------------------------------------------
    # [규칙 1] 텍스트 + 스티커
    if user_text == "안녕하이소":
        reply_messages.append(TextMessage(text="안녕하세요! 무엇을 도와드릴까요?"))
        reply_messages.append(StickerMessage(package_id="11537", sticker_id="52002734"))

    # [/ㅁㄷㅅ 숫자] 명령어 처리
    elif re.match(r"^/ㅁㄷㅅ\s+\d+$", user_text):
        if "🎪" not in user_nickname:
            reply_messages.append(TextMessage(text=f"⚠️ 권한이 없습니다. (인식된 닉네임: {user_nickname})"))
        else:
            n = int(user_text.split()[1])

            top_users = get_ranked_users(limit=n, order="DESC")
            bottom_users = get_ranked_users(limit=n, order="ASC")

            if top_users:
                msg = f"🏆 소통왕 (상위 {n}명)\n"
                for idx, (nick, count, length) in enumerate(top_users, 1):
                    msg += f"{idx}위: {nick} - {count}회 ({length}자)\n"

                msg += "\n"

                msg += f"💤 조용한 사람 (하위 {n}명)\n"
                for idx, (nick, count, length) in enumerate(bottom_users, 1):
                    msg += f"{idx}위: {nick} - {count}회 ({length}자)\n"

                reply_messages.append(TextMessage(text=msg.strip()))
            else:
                reply_messages.append(TextMessage(text="오늘 집계된 기록이 없습니다."))

    # --------------------------------------------------
    # 4. 답장 메시지 전송 (응답할 메시지가 있을 때만 전송)
    # --------------------------------------------------
    if reply_messages:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=reply_messages
                )
            )

# ==============================================================================
# 6. 서버 실행
# ==============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
