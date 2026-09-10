# ==============================================================================
# 1. 라이브러리 및 모듈 임포트
# ==============================================================================
# 파이썬 표준 라이브러리 (기본 모듈)
import os                                  # 서버 환경변수(LINE API 키 등) 로드용
import re                                  # 정규표현식 명령어 파싱용 (/ㅁㄷㅅ, /마딧수, /ㅈㅅㅇ 등)
import sqlite3                             # DB 연동 및 유저 통계 / 이미지 키워드 저장용
import random                              # 주사위(/ㅈㅅㅇ) 기능용 랜덤 모듈
import requests                            # ImgBB 외부 이미지 호스팅 API 전송용
from datetime import datetime              # 최근 활동 시간(last_active) 기록용

# Flask 웹 프레임워크
from flask import Flask, request, abort   # 웹 서버 구축 및 라인 웹훅 수신용

# LINE Messaging API SDK v3 모듈
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,                      # 바이너리 이미지 다운로드용
    ReplyMessageRequest,
    TextMessage,
    ImageMessage,                          # 이미지 답장 전송용
    StickerMessage
)
from linebot.v3.webhooks import (
    MessageEvent, 
    TextMessageContent, 
    ImageMessageContent,                   # 유저가 업로드한 이미지 이벤트 처리용
    MemberJoinedEvent,                     # 멤버 입장 스캔용
    MemberLeftEvent                        # 멤버 퇴장 자동 삭제용
)

# APScheduler (자정 리셋 스케줄러)
from apscheduler.schedulers.background import BackgroundScheduler  # 자정(00:00 KST) 데이터 정제용

# ==============================================================================
# 2. Flask 서버 및 LINE API / ImgBB 설정
# ==============================================================================
app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
IMGBB_API_KEY = os.environ.get('IMGBB_API_KEY')

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ==============================================================================
# 3. 데이터베이스 및 스케줄러 설정
# ==============================================================================
def init_db():
    conn = sqlite3.connect('chat_stats.db')
    cursor = conn.cursor()
    # 1) 유저 통계 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id TEXT PRIMARY KEY,
            nickname TEXT,
            msg_count INTEGER DEFAULT 0,
            talk_length INTEGER DEFAULT 0,
            last_active DATETIME
        )
    ''')
    # 2) 이미지 저장용 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bot_images (
            keyword TEXT PRIMARY KEY,
            image_url TEXT
        )
    ''')
    # 3) 이미지 등록 대기 상태 저장용 테이블 (Render 멀티프로세스 환경용)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_uploads (
            user_id TEXT PRIMARY KEY,
            keyword TEXT
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
    """매일 자정(00:00 KST): 유저 목록 유지, 카운트만 0으로 리셋"""
    conn = sqlite3.connect('chat_stats.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE user_stats SET msg_count = 0, talk_length = 0')
    conn.commit()
    conn.close()
    print("🧹 [자정 정제 완료] 유저 목록은 유지되며 카운트가 0으로 초기화되었습니다.")

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
# 5. 이벤트 핸들러 (입장 / 퇴장 / 메시지)
# ==============================================================================

# ① 멤버 입장 이벤트
@handler.add(MemberJoinedEvent)
def handle_member_joined(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        for member in event.joined.members:
            u_id = member.user_id
            nick = "새멤버"
            try:
                profile = line_bot_api.get_group_member_profile(event.source.group_id, u_id)
                nick = profile.display_name
            except Exception as e:
                print(f"입장 프로필 조회 실패: {e}")
            
            conn = sqlite3.connect('chat_stats.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_stats (user_id, nickname, msg_count, talk_length, last_active)
                VALUES (?, ?, 0, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET nickname = excluded.nickname
            ''', (u_id, nick, datetime.now()))
            conn.commit()
            conn.close()

# ② 멤버 퇴장 이벤트
@handler.add(MemberLeftEvent)
def handle_member_left(event):
    conn = sqlite3.connect('chat_stats.db')
    cursor = conn.cursor()
    for member in event.left.members:
        u_id = member.user_id
        cursor.execute('DELETE FROM user_stats WHERE user_id = ?', (u_id,))
    conn.commit()
    conn.close()

# ③ 텍스트 메시지 수신 및 자동응답 처리
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

    # 2. 활동 카운트 업데이트
    current_text_len = len(user_text)
    update_user_activity(user_id, user_nickname, current_text_len)

    # 3. 이미지 키워드 단독 입력 체킹 (DB 조회)
    conn = sqlite3.connect('chat_stats.db')
    cursor = conn.cursor()
    cursor.execute("SELECT image_url FROM bot_images WHERE keyword = ?", (user_text,))
    img_row = cursor.fetchone()
    conn.close()

    # ① 등록된 이미지 키워드와 정확히 일치 시
    if img_row:
        image_url = img_row[0]
        reply_messages.append(
            ImageMessage(
                originalContentUrl=image_url,
                previewImageUrl=image_url
            )
        )

    # ② 인사 테스트
    elif user_text == "안녕하이소":
        reply_messages.append(TextMessage(text="안녕하세요! 무엇을 도와드릴까요?"))
        reply_messages.append(StickerMessage(package_id="11537", sticker_id="52002734"))

    # ③ /이미지등록 [키워드] (🎪 권한 필요)
    elif user_text.startswith("/이미지등록 "):
        if "🎪" not in user_nickname:
            reply_messages.append(TextMessage(text=f"⚠️ 권한이 없습니다. (인식된 닉네임: {user_nickname})"))
        else:
            keyword = user_text.split(" ", 1)[1].strip()
            if not keyword:
                reply_messages.append(TextMessage(text="⚠️ 키워드를 입력해주세요. (예: /이미지등록 강아지)"))
            else:
                conn = sqlite3.connect('chat_stats.db')
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO pending_uploads (user_id, keyword) VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET keyword = excluded.keyword
                ''', (user_id, keyword))
                conn.commit()
                conn.close()
                reply_messages.append(TextMessage(text=f"📸 '{keyword}' 키워드로 저장할 이미지를 지금 바로 올려주세요!"))

    # ④ /이미지삭제 [키워드] (🎪 권한 필요)
    elif user_text.startswith("/이미지삭제 "):
        if "🎪" not in user_nickname:
            reply_messages.append(TextMessage(text=f"⚠️ 권한이 없습니다. (인식된 닉네임: {user_nickname})"))
        else:
            keyword = user_text.split(" ", 1)[1].strip()
            if not keyword:
                reply_messages.append(TextMessage(text="⚠️ 삭제할 키워드를 입력해주세요. (예: /이미지삭제 강아지)"))
            else:
                conn = sqlite3.connect('chat_stats.db')
                cursor = conn.cursor()
                cursor.execute("SELECT keyword FROM bot_images WHERE keyword = ?", (keyword,))
                exists = cursor.fetchone()
                
                if exists:
                    cursor.execute("DELETE FROM bot_images WHERE keyword = ?", (keyword,))
                    conn.com
