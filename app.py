# ==============================================================================
# 1. 라이브러리 및 모듈 임포트
# ==============================================================================
import os  # 서버 환경변수(보안 토큰 등) 접근용 모듈
from flask import Flask, request, abort  # 파이썬 웹 프레임워크 및 요청 처리

# LINE SDK에서 메시지 수신/검증/전송에 필요한 클래스 가져오기
from linebot.v3 import WebhookHandler  # 보안 서명 검증 클래스
from linebot.v3.exceptions import InvalidSignatureError  # 서명 에러 처리
from linebot.v3.messaging import (
    Configuration,       # API 설정 클래스
    ApiClient,           # 라인 서버 통신 클라이언트
    MessagingApi,        # 메시지 전송 API 클래스
    ReplyMessageRequest, # 답장 요청 데이터 구조
    TextMessage,         # 텍스트 메시지 객체
    ImageMessage,        # 이미지 메시지 객체
    StickerMessage       # 스티커(이모티콘) 메시지 객체
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent  # 웹훅 이벤트 구조

# ==============================================================================
# 2. Flask 서버 및 LINE API 설정
# ==============================================================================
app = Flask(__name__)  # Flask 웹 서버 객체 생성

# Render 환경변수에서 라인 키 값 로드
CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')  # 액세스 토큰
CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')              # 시크릿 키

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)  # API 토큰 설정
handler = WebhookHandler(CHANNEL_SECRET)                          # 서명 검증기 설정

# ==============================================================================
# 3. LINE 웹훅 수신 경로 (/callback)
# ==============================================================================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')  # 라인이 보낸 보안 서명 추출
    body = request.get_data(as_text=True)                 # 수신된 메시지 데이터 텍스트 변환

    try:
        handler.handle(body, signature)  # 서명 검증 후 메시지 이벤트 핸들러로 전달
    except InvalidSignatureError:
        abort(400)  # 서명이 유효하지 않으면 400 에러 반환
    return 'OK'     # 라인 서버에 정상 수신 알림

# ==============================================================================
# 4. 키워드별 자동응답 메시지 처리
# ==============================================================================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()  # 유저가 입력한 텍스트 (공백 제거)
    reply_messages = []                     # 전송할 메시지 목록 (최대 5개 가능)

    # [규칙 1] 텍스트 + 이모티콘(스티커) 함께 전송
    if "안녕" in user_text or "반가워" in user_text:
        reply_messages.append(TextMessage(text="안녕하세요! 무엇을 도와드릴까요?"))  # 텍스트 추가
        reply_messages.append(StickerMessage(package_id="11537", sticker_id="52002734"))  # 스티커 추가

    # [규칙 1] 텍스트 + 이모티콘(스티커) 함께 전송
    if "/ㅁㅅ" in user_text:


        reply_messages.append(StickerMessage(package_id="11537", sticker_id="52002734"))  # 스티커 추가
    
    # [규칙 2] 텍스트 + 이미지 함께 전송
    elif "위치" in user_text or "약도" in user_text:
        reply_messages.append(TextMessage(text="📍 저희 매장 오시는 길 위치 안내입니다."))  # 텍스트 추가
        sample_map_url = "https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1"   # 이미지 HTTPS URL
        reply_messages.append(ImageMessage(
            original_content_url=sample_map_url,  # 원본 이미지 URL
            preview_image_url=sample_map_url      # 미리보기 이미지 URL
        ))

    # [규칙 3] 텍스트만 전송
    elif "영업시간" in user_text:
        reply_messages.append(TextMessage(text="⏰ 영업시간 안내\n- 평일: 09:00 ~ 18:00\n- 주말/공휴일: 휴무"))
    
    # [규칙 3] 텍스트만 전송
    elif "ㅁㄴ" in user_text:
        reply_messages.append(StickerMessage(package_id="11537", sticker_id="52002734"))
        reply_messages.append(StickerMessage(package_id="11537", sticker_id="52002734"))
        reply_messages.append(StickerMessage(package_id="11537", sticker_id="52002734"))
        reply_messages.append(StickerMessage(package_id="11537", sticker_id="52002734"))

    
    # [기타] 등록되지 않은 키워드가 입력되었을 때
    else:

    # 라인 서버로 답장 보내기
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)  # API 클라이언트 생성
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,  # 일회성 답장 토큰
                messages=reply_messages         # 응답할 메시지 배열
            )
        )

# ==============================================================================
# 5. 서버 실행
# ==============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # 외부 포트 지정 (기본 5000)
    app.run(host="0.0.0.0", port=port)        # 모든 IP에 대해 서버 실행
