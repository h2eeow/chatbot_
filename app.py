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

    # 2. 활동 카운트 및 글자 수 업데이트 (항상 기록)
    current_text_len = len(user_text)
    update_user_activity(user_id, user_nickname, current_text_len)

    # ==========================================================================
    # 🎯 [1순위] DB 이미지 키워드 검사 (일치하면 즉시 전송 후 리턴)
    # ==========================================================================
    conn = sqlite3.connect('chat_stats.db')
    cursor = conn.cursor()
    cursor.execute("SELECT image_url FROM bot_images WHERE keyword = ?", (user_text,))
    img_row = cursor.fetchone()
    conn.close()

    if img_row:
        image_url = img_row[0]
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[
                        ImageMessage(
                            originalContentUrl=image_url,
                            previewImageUrl=image_url
                        )
                    ]
                )
            )
        return  # 이미지를 보냈으므로 여기서 처리 종료!

    # ==========================================================================
    # 🎯 [2순위] 일반 텍스트 명령어 및 자동응답 처리
    # ==========================================================================
    if user_text == "안녕하이소":
        reply_messages.append(TextMessage(text="안녕하세요! 무엇을 도와드릴까요?"))
        reply_messages.append(StickerMessage(package_id="11537", sticker_id="52002734"))

    # /이미지등록 [키워드] (🎪 권한 필요)
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

    # /이미지삭제 [키워드] (🎪 권한 필요)
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
                    conn.commit()
                    reply_messages.append(TextMessage(text=f"🗑️ '{keyword}' 키워드의 이미지가 삭제되었습니다."))
                else:
                    reply_messages.append(TextMessage(text=f"⚠️ '{keyword}' 키워드로 등록된 이미지가 없습니다."))
                
                conn.close()

    # /ㅁㄷㅅ [숫자] (상세 통계)
    elif re.match(r"^/ㅁㄷㅅ\s+\d+$", user_text):
        if "🎪" not in user_nickname:
            reply_messages.append(TextMessage(text=f"⚠️ 권한이 없습니다. (인식된 닉네임: {user_nickname})"))
        else:
            n = int(user_text.split()[1])
            top_users = get_ranked_users(limit=n, order="DESC")
            bottom_users = get_ranked_users(limit=n, order="ASC")

            if top_users:
                medals = ["🥇", "🥈", "🥉"]

                msg = f"🏆 소통왕 (상위 {n}명)\n\n"
                for idx, (nick, count, length) in enumerate(top_users, 1):
                    display_nick = nick[1:] if len(nick) > 1 else nick
                    rank_prefix = medals[idx - 1] if idx <= 3 else f"{idx}위"
                    msg += f"{rank_prefix} {display_nick}\n💬 {count}개 · ✏️ {length}자\n\n"

                msg += "───────────────────\n\n"

                msg += f"💤 조용한 사람 (하위 {n}명)\n\n"
                for idx, (nick, count, length) in enumerate(bottom_users, 1):
                    display_nick = nick[1:] if len(nick) > 1 else nick
                    msg += f"💤 {idx}위 {display_nick}\n💬 {count}개 · ✏️ {length}자\n\n"

                reply_messages.append(TextMessage(text=msg.strip()))
            else:
                reply_messages.append(TextMessage(text="오늘 집계된 기록이 없습니다."))

    # 주사위 기능 (/ㅈㅅㅇ)
    elif user_text == "/ㅈㅅㅇ":
        dice_num = random.randint(1, 6)
        reply_messages.append(TextMessage(text=f"🎲 주사위 결과: {dice_num}"))

    elif re.match(r"^/ㅈㅅㅇ\s+\d+$", user_text):
        max_num = int(user_text.split()[1])
        if max_num < 1:
            reply_messages.append(TextMessage(text="⚠️ 1 이상의 숫자를 입력해주세요!"))
        else:
            dice_num = random.randint(1, max_num)
            reply_messages.append(TextMessage(text=f"🎲 주사위 결과 (1~{max_num}): {dice_num}"))

    # 답장 메시지가 있을 경우 전송
    if reply_messages:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=reply_messages
                )
            )
