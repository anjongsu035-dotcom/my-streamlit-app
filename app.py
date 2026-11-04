# =========================================================
# AIVLE — 김 대리의 음성 AI 개인비서 (음성으로는 '에이블'이라고 부릅니다)
# KT AIVLE School 미니프로젝트 3차
#
# 구성
#   1) 설정   : 라이브러리, 상수, Secrets, OpenAI, 팀 주소록(데모), CSS
#   2) 공용 저장소 : 앱 안 캘린더(일정·요청)를 모든 접속자가 함께 보는 메모리 저장소 (st.cache_resource)
#   3) 상태   : session_state 초기화
#   4) 도구 함수 : 날짜/이메일(데모 발송)/업무/요청 등 순수 함수
#   5) LLM    : 회의록 분석(구조화 출력), 대화(함수 호출 루프), 초안 작성, STT, TTS
#   6) 다이얼로그 : 캘린더 추가 / 메일 발송 / 일정 보기 / 협업·미팅 요청 / 업무 초안
#   7) 화면   : 사이드바(보기 모드 + 메뉴) + 페이지별 render 함수 + main()
#
# 데모 전제
#   - 캘린더는 앱 안 저장소만 사용 (구글 캘린더 연동 없음). 앱이 재시작/재배포되면 초기화됩니다.
#   - '메일 보내기' 확인 창에서 입력한 주소로 실제 발송합니다. 협업·미팅 요청 알림은 팀원 주소가 가상이라 MY_EMAIL 로 보냅니다.
# =========================================================

import os, re, json, html, hashlib, uuid, smtplib, threading, base64
import calendar as cal_lib
from datetime import date, datetime, time, timedelta, timezone
from email.mime.text import MIMEText
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor

import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI


# =========================================================
# 1) 설정
# =========================================================
st.set_page_config(page_title="AIVLE — 김 대리의 AI 비서", page_icon="◆", layout="wide", initial_sidebar_state="expanded")

APP_NAME = "AIVLE"
USER_NAME = "김 대리"
KST = timezone(timedelta(hours=9))          # 한국 시간 (서머타임 없음)
LLM_MODEL = "gpt-4o-mini"
STT_MODEL = "whisper-1"
TTS_MODEL = "gpt-4o-mini-tts"               # 실패하면 tts-1 로 재시도
TTS_VOICE = "alloy"
MAX_TURNS = 10                              # 대화 기록 유지 턴 수
WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"]
WEEKDAY_EN = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
STEP_LABELS = ["회의록 올리기", "업무 확인 · 일정 등록", f"{APP_NAME}에게 부탁하기"]
PAGES = {"assistant": f"{APP_NAME}에게 부탁하기", "summary": "회의록 요약", "tasks": "내 업무", "calendar": "캘린더", "requests": "받은 요청"}
DEFAULT_MY_EMAIL = "totomwoo@gmail.com"     # MY_EMAIL Secrets 가 없을 때 쓰는 기본 수신자 (사용자 승인)
REQUEST_TYPES = ["미팅 요청", "협업 요청"]
DURATIONS = [30, 60, 90]

# 팀 주소록 (가상 주소). 김 대리는 MY_EMAIL. 메일 확인 창에서는 가상 주소를 비워 두고 실제 주소를 입력받는다.
DEMO_CONTACTS = [
    ("팀장", "teamlead@aivle-demo.kr"),
    ("박과장", "park@aivle-demo.kr"),
    ("이과장", "lee@aivle-demo.kr"),
    ("최대리", "choi@aivle-demo.kr"),
]

# 도구 실행 결과를 화면에 보여줄 때 쓰는 한국어 문구 ({n} = 건수)
TOOL_LABELS = {
    ("list_events", "done"): "일정 조회함",
    ("add_calendar_event", "waiting"): "캘린더 추가 — 확인 대기",
    ("add_calendar_event", "done"): "캘린더에 {n}건 추가함",
    ("add_calendar_event", "cancelled"): "캘린더 추가 취소함",
    ("add_calendar_event", "skipped"): "이미 캘린더에 있는 업무",
    ("send_email", "waiting"): "메일 발송 — 확인 대기",
    ("send_email", "done"): "메일 보냄",
    ("send_email", "cancelled"): "메일 발송 취소함",
    ("request", "sent"): "협업·미팅 요청 {n}명에게 보냄",
}

# 파일 없이도 시연할 수 있는 샘플 회의록 (교안 meeting.txt)
SAMPLE_MEETING_NAME = "meeting.txt (샘플)"
SAMPLE_MEETING = """팀장: 오늘 미팅을 시작하겠습니다. 오늘 주제는 신제품 출시 마케팅 전략입니다.
박과장: 김대리가 외출 중이라 오늘 회의에는 참석하지 못했습니다.
최대리: 제가 나중에 김대리에게 미팅 기록을 전달하겠습니다.
팀장: 네, 그렇게 해주세요. 김대리도 내용은 꼭 알아야 합니다.
이과장: 이번 신제품은 다음 달 초 출시 예정이라 마케팅 준비를 서둘러야 합니다.
팀장: 맞습니다. 우선 전체적인 마케팅 방향부터 정해보죠.
박과장: 저는 온라인 중심으로 마케팅을 진행하는 것이 좋다고 생각합니다.
이과장: 요즘은 SNS 광고가 가장 효과적이니까요.
최대리: 특히 인스타그램과 유튜브가 좋을 것 같습니다.
팀장: 네, SNS 마케팅은 기본으로 가져가야겠네요.
박과장: 그리고 경쟁사 사례를 분석해 보면 좋겠습니다.
팀장: 좋은 의견입니다. 경쟁사들이 어떤 마케팅을 하는지 파악해야 합니다.
이과장: 최근 경쟁사 A사가 SNS 캠페인을 크게 진행했습니다.
최대리: 맞습니다. 인플루언서를 활용한 캠페인이었습니다.
팀장: 그렇다면 우리도 경쟁사 마케팅을 분석할 필요가 있겠네요.
박과장: 김대리가 데이터 분석을 잘하니까 그 업무를 맡기면 어떨까요?
팀장: 좋습니다. 김대리에게 경쟁사 온라인 마케팅 사례 분석을 맡기죠.
최대리: 네, 제가 김대리에게 경쟁사 마케팅 분석 업무가 할당됐다고 전달하겠습니다.
이과장: 분석 보고서를 작성해서 공유하면 좋겠습니다.
팀장: 네, 김대리가 경쟁사 SNS 광고와 프로모션 사례를 정리하면 좋겠습니다.
박과장: 보고서는 다음 주까지 받으면 좋겠습니다.
팀장: 좋습니다. 다음 안건으로 넘어가겠습니다.
이과장: 신제품 홍보 채널을 정해야 할 것 같습니다.
박과장: 인스타그램 광고는 꼭 진행해야 합니다.
최대리: 유튜브 리뷰 콘텐츠도 필요할 것 같습니다.
팀장: 유튜브 인플루언서 협업도 고려해보죠.
이과장: 요즘은 틱톡도 영향력이 커졌습니다.
박과장: 맞습니다. 젊은 층을 타겟으로 할 때 효과적입니다.
팀장: SNS 콘텐츠 기획도 필요합니다.
최대리: 콘텐츠 아이디어를 정리해야 할 것 같습니다.
박과장: 콘텐츠 초안은 누가 작성하면 좋을까요?
팀장: 김대리가 콘텐츠 기획도 잘하니까 SNS 홍보 콘텐츠 초안을 맡기면 어떨까요?
이과장: 좋은 생각입니다.
최대리: 그럼 김대리에게 SNS 홍보 콘텐츠 초안 작성도 부탁하는 걸로 하겠습니다.
팀장: 네, 김대리에게 두 가지 업무가 있겠네요.
박과장: 경쟁사 마케팅 분석과 SNS 콘텐츠 초안 작성이군요.
팀장: 맞습니다.
이과장: 콘텐츠 방향도 미리 정해두면 좋겠습니다.
팀장: 어떤 방향이 좋을까요?
박과장: 제품 기능을 강조하는 콘텐츠가 좋겠습니다.
최대리: 사용 후기 형식의 콘텐츠도 좋을 것 같습니다.
이과장: 짧은 영상 콘텐츠도 필요할 것 같습니다.
팀장: 네, 요즘은 숏폼 콘텐츠가 중요합니다.
박과장: SNS 광고 예산도 논의해야 합니다.
팀장: 이번 프로젝트 예산은 어느 정도인가요?
이과장: 전체 마케팅 예산은 약 5천만 원입니다.
팀장: SNS 광고에 절반 정도 사용할 수 있겠네요.
박과장: 인플루언서 협업 비용도 고려해야 합니다.
최대리: 중급 인플루언서 3명 정도 협업하면 좋겠습니다.
팀장: 후보 인플루언서를 조사해야 합니다.
박과장: 그 작업도 김대리가 하면 어떨까요?
이과장: 네, 김대리가 SNS 데이터 조사도 잘합니다.
팀장: 좋습니다. 김대리에게 인플루언서 후보 리스트 조사도 부탁합시다.
최대리: 제가 김대리에게 업무 내용을 정리해서 전달하겠습니다.
팀장: 감사합니다.
박과장: 그러면 김대리 업무가 세 가지네요.
이과장: 경쟁사 마케팅 분석, SNS 콘텐츠 초안 작성, 인플루언서 후보 조사입니다.
팀장: 맞습니다. 회의록에도 그렇게 정리해주세요.
최대리: 네, 김대리에게 전달할 때도 명확히 설명하겠습니다.
팀장: 다음으로 광고 일정에 대해 이야기해보죠.
박과장: 출시 2주 전부터 광고를 시작하면 좋겠습니다.
이과장: 티저 콘텐츠를 먼저 올리는 것도 좋겠습니다.
최대리: 티저 영상은 제작이 필요합니다.
팀장: 영상 제작 업체도 알아봐야겠네요.
박과장: 디자인팀과 협의하면 될 것 같습니다.
이과장: 랜딩 페이지도 준비해야 합니다.
팀장: 맞습니다. 구매 페이지도 필요합니다.
최대리: SNS에서 랜딩 페이지로 유도하면 좋겠습니다.
박과장: 할인 이벤트도 고려해야 합니다.
팀장: 초기 프로모션은 어떤 것이 좋을까요?
이과장: 출시 기념 할인 이벤트가 좋겠습니다.
최대리: SNS 공유 이벤트도 효과적입니다.
팀장: 좋습니다. 이벤트 기획도 진행해봅시다.
박과장: 이벤트 경품은 제품으로 하면 될 것 같습니다.
이과장: 참여 조건은 SNS 팔로우와 공유로 하면 좋겠습니다.
팀장: 전체 일정은 다음 주에 다시 점검합시다.
박과장: 네, 다음 회의에서 진행 상황을 공유하겠습니다.
최대리: 김대리에게는 오늘 논의된 업무를 바로 전달하겠습니다.
팀장: 꼭 전달해주세요.
이과장: 특히 경쟁사 마케팅 분석 보고서는 중요합니다.
박과장: SNS 콘텐츠 초안도 빨리 받아야 합니다.
팀장: 인플루언서 후보 리스트도 같이 부탁한다고 전해주세요.
최대리: 네, 김대리에게 세 가지 업무를 명확히 전달하겠습니다.
팀장: 좋습니다.
박과장: 오늘 회의 내용은 회의록으로 정리하겠습니다.
이과장: 김대리도 회의록을 보면 이해할 수 있을 겁니다.
최대리: 제가 회의록 파일을 김대리에게 보내겠습니다.
팀장: 모두 수고하셨습니다.
박과장: 감사합니다.
이과장: 수고하셨습니다.
최대리: 회의 종료하겠습니다.
"""


def get_secret(name, default=None):
    """환경 변수 → st.secrets 순서로 읽는다. (Cloud의 최상위 Secrets는 환경 변수로도 제공됨)"""
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets[name]
    except Exception:
        return default


OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
GMAIL_ADDRESS = get_secret("GMAIL_ADDRESS")          # 발신 계정 (기본값 없음)
GMAIL_APP_PASSWORD = get_secret("GMAIL_APP_PASSWORD")
MY_EMAIL = get_secret("MY_EMAIL") or DEFAULT_MY_EMAIL  # 모든 메일이 실제로 도착하는 곳
APP_URL = (get_secret("APP_URL") or "").rstrip("/")   # 요청 메일에 넣을 앱 주소 (없으면 링크 생략)
GMAIL_OK = bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD)
CONTACTS = [(USER_NAME, MY_EMAIL)] + DEMO_CONTACTS
CONTACT_EMAIL = dict(CONTACTS)
TEAMMATES = [name for name, _ in DEMO_CONTACTS]


@st.cache_resource(show_spinner=False)
def get_openai_client(api_key):
    return OpenAI(api_key=api_key)


client = get_openai_client(OPENAI_API_KEY) if OPENAI_API_KEY else None


# ---- 디자인 토큰 / CSS (보라 팔레트) ----
# 원칙: 스타일만 바꾼다. Streamlit 구성요소를 숨기지 않고, Material 아이콘(span[data-testid="stIconMaterial"]) 에는 글꼴을 적용하지 않는다.
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap');
:root{--primary:#5B4BE0;--primary-dark:#4F3FD0;--primary-text:#4338CA;--tint:#EDE9FE;--tint2:#F4F3FF;--border:#DDD6FE;--sidebar-border:#E0DDFB;
--text:#1E1B4B;--muted:#5B5F7A;--text2:#3F3F5F;--dark:#1E1B4B;
--task:#1D4ED8;--task-tint:#DBEAFE;--task-border:#BFDBFE;--task-row:#F5F8FF;
--cal:#047857;--cal-tint:#D1FAE5;--cal-bg:#F0FDF4;--cal-text:#065F46;
--warn:#92400E;--warn-bg:#FEF3C7;--ok:#10B981;--shadow:0 10px 30px rgba(91,75,224,.10);}
.stApp{background:linear-gradient(160deg,#EFEBFF 0%,#E7EEFF 55%,#E3F3FF 100%);color:var(--text);font-family:'Noto Sans KR',sans-serif;}
div.stApp :where(*:not([data-testid="stIconMaterial"]):not([data-testid="stIconEmoji"]):not([class*="material"]):not([translate="no"]):not(code):not(pre):not(kbd):not(svg):not(svg *)),
[data-testid="stDialog"] :where(*:not([data-testid="stIconMaterial"]):not([data-testid="stIconEmoji"]):not([class*="material"]):not([translate="no"]):not(code):not(pre):not(kbd):not(svg):not(svg *)){font-family:'Noto Sans KR',sans-serif;}
.stApp .aivle-wordmark{font-family:'Poppins',sans-serif;}
header[data-testid="stHeader"]{background:transparent;}
.block-container{padding:28px 32px 40px;max-width:1180px;}
@media (max-width:1100px){.block-container{padding:20px 16px 32px;}}
/* 사이드바 */
[data-testid="stSidebar"]{background:rgba(255,255,255,.72);border-right:1px solid var(--sidebar-border);}
[data-testid="stSidebar"] .stButton>button{width:100%;justify-content:flex-start;min-height:48px;border-radius:14px;border:none;background:transparent;color:var(--text);font-size:15px;box-shadow:none;}
[data-testid="stSidebar"] .stButton>button:hover{background:var(--tint2);color:var(--text);border:none;}
[data-testid="stSidebar"] .st-key-nav_assistant button[kind="primary"]{background:var(--primary);color:#fff;font-weight:500;}
[data-testid="stSidebar"] .st-key-nav_tasks button[kind="primary"]{background:var(--task);color:#fff;font-weight:500;}
[data-testid="stSidebar"] .st-key-nav_calendar button[kind="primary"]{background:var(--cal);color:#fff;font-weight:500;}
[data-testid="stSidebar"] .st-key-nav_requests button[kind="primary"]{background:var(--primary);color:#fff;font-weight:500;}
[data-testid="stSidebar"] .st-key-btn_reset button,[data-testid="stSidebar"] .st-key-btn_reset_yes button,[data-testid="stSidebar"] .st-key-btn_reset_no button{min-height:34px;font-size:12px;color:var(--muted);justify-content:center;border:1px solid var(--border);}
[data-testid="stSidebar"] .st-key-btn_reset_yes button{color:#B91C1C;border-color:#FCA5A5;}
.aivle-brand{display:flex;align-items:center;gap:10px;padding:4px 8px 12px;}
.aivle-brand i{width:40px;height:40px;border-radius:12px;background:var(--primary);display:inline-flex;align-items:center;justify-content:center;color:#fff;font-style:normal;font-weight:700;}
.aivle-wordmark{font-size:22px;font-weight:700;color:var(--text);}
.aivle-conn{display:flex;flex-direction:column;gap:8px;padding:12px;border-radius:14px;background:#fff;font-size:13px;color:var(--text2);}
.aivle-conn span{display:inline-flex;align-items:center;gap:6px;}
.aivle-conn i{width:8px;height:8px;border-radius:50%;display:inline-block;flex:0 0 8px;}
.aivle-steps{display:flex;flex-direction:column;gap:4px;padding:0 8px;font-size:12px;color:var(--muted);}
.aivle-step{display:flex;align-items:center;gap:8px;}
.aivle-step i{font-style:normal;width:18px;height:18px;border-radius:50%;border:1px solid var(--border);display:inline-flex;align-items:center;justify-content:center;font-size:11px;}
.aivle-step-now{color:var(--text);font-weight:700;}
.aivle-step-now i{background:var(--primary);color:#fff;border-color:var(--primary);}
.aivle-step-done i{background:var(--cal-tint);color:var(--cal-text);border-color:var(--cal-tint);}
/* 기본 버튼 */
.stButton>button,.stFormSubmitButton>button{border-radius:12px;border:1px solid var(--border);background:#fff;color:var(--primary-text);font-size:14px;min-height:44px;padding:0 16px;box-shadow:none;white-space:normal;line-height:1.3;}
.stButton>button:hover,.stFormSubmitButton>button:hover{border-color:var(--primary);color:var(--primary-text);background:var(--tint2);}
.stButton>button[kind="primary"]{background:var(--primary);color:#fff;border-color:var(--primary);font-weight:500;}
.stButton>button[kind="primary"]:hover{background:var(--primary-dark);color:#fff;border-color:var(--primary-dark);}
.stButton>button:disabled{opacity:.5;}
.st-key-page_tasks .stButton>button{color:var(--task);border-color:var(--task-border);}
.st-key-page_tasks .stButton>button[kind="primary"]{background:var(--task);border-color:var(--task);color:#fff;}
.st-key-page_tasks .stButton>button[kind="primary"]:hover{background:#1E40AF;border-color:#1E40AF;color:#fff;}
.st-key-page_calendar .stButton>button{color:var(--cal);border-color:#A7F3D0;}
.st-key-page_calendar .stButton>button[kind="primary"]{background:var(--cal);border-color:var(--cal);color:#fff;}
[class*="st-key-chip_"] button{border-radius:999px;min-height:40px;}
[class*="st-key-tlink_"] button{width:100%;justify-content:flex-start;text-align:left;border-color:var(--task-border);color:var(--text);border-radius:16px;background:#fff;}
[class*="st-key-tlink_"] button:hover{background:var(--task-row);border-color:var(--task);color:var(--text);}
[class*="st-key-up_"] button,[class*="st-key-sent_"] button{width:100%;justify-content:flex-start;text-align:left;border-radius:14px;color:var(--text);border-color:var(--tint);background:var(--tint2);min-height:40px;font-size:13px;}
.st-key-card_chat .stFormSubmitButton>button{background:var(--dark);color:#fff;border-color:var(--dark);border-radius:999px;min-height:48px;font-weight:500;}
.st-key-card_chat .stFormSubmitButton>button:hover{background:#312E81;color:#fff;}
/* 입력: 밝은 바탕 + 어두운 글자 (상속에 맡기지 않음) */
[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="textarea"]{border-radius:14px!important;background:#fff!important;border-color:var(--border)!important;}
.stApp input,.stApp textarea,[data-testid="stDialog"] input,[data-testid="stDialog"] textarea{color:var(--text)!important;-webkit-text-fill-color:var(--text)!important;}
.stApp input::placeholder,.stApp textarea::placeholder{color:var(--muted)!important;-webkit-text-fill-color:var(--muted)!important;opacity:1;}
.st-key-card_chat [data-baseweb="input"],.st-key-card_chat [data-baseweb="base-input"]{background:var(--tint2)!important;border-radius:999px!important;border-color:transparent!important;}
[data-testid="stFileUploaderDropzone"]{border:1px dashed var(--primary);border-radius:16px;background:var(--tint2);}
[data-testid="stFileUploader"] [data-testid="stWidgetLabel"] p{font-size:16px;font-weight:700;}
/* 카드 */
.st-key-card_meeting,.st-key-card_upload,.st-key-card_chat,.st-key-card_calendar,.st-key-card_upcoming,.st-key-card_sent,.st-key-card_empty,[class*="st-key-task_card_"],[class*="st-key-task_sel_"],[class*="st-key-req_"]{background:#fff;border-radius:24px;padding:20px 24px;box-shadow:var(--shadow);box-sizing:border-box;max-width:100%;min-width:0;}
[class*="st-key-task_sel_"]{box-shadow:0 0 0 3px var(--task),0 16px 40px rgba(29,78,216,.15);}
[class*="st-key-req_focus_"]{box-shadow:0 0 0 3px var(--primary),0 16px 40px rgba(91,75,224,.18);}
.aivle-eyebrow{font-size:13px;color:var(--muted);margin:0;}
.aivle-strong{font-size:16px;font-weight:700;margin:0;overflow-wrap:anywhere;}
.aivle-h1{font-size:28px;font-weight:700;margin:0;line-height:1.3;}
.aivle-h1 b{color:var(--task);}
.aivle-hint{font-size:14px;color:var(--muted);margin:4px 0 0;line-height:1.6;}
.aivle-note{font-size:14px;line-height:1.6;color:var(--text2);margin:8px 0 0;padding:10px 14px;border-radius:14px;background:#fff;border:1px solid var(--border);}
.aivle-tag{display:inline-block;padding:4px 10px;border-radius:999px;background:var(--task-tint);color:var(--task);font-size:12px;font-weight:700;margin-right:6px;}
.aivle-tag-p{background:var(--tint);color:var(--primary-text);}
.aivle-tag-ok{background:var(--cal-tint);color:var(--cal-text);}
.aivle-tag-x{background:#FEE2E2;color:#991B1B;}
.aivle-tag-w{background:var(--warn-bg);color:var(--warn);}
.aivle-num{width:40px;height:40px;border-radius:12px;background:var(--task-tint);color:var(--task);font-weight:700;display:inline-flex;align-items:center;justify-content:center;}
.aivle-task-title{font-size:18px;font-weight:700;margin:0;}
.aivle-task-meta{font-size:14px;color:var(--muted);margin:2px 0 0;}
.aivle-warn{color:var(--warn);font-weight:500;}
.aivle-done{display:inline-flex;align-items:center;gap:6px;min-height:40px;padding:0 14px;border-radius:12px;background:var(--cal-tint);color:var(--cal-text);font-size:14px;font-weight:500;margin-bottom:6px;}
/* 대화 */
.aivle-msg-u{display:flex;flex-direction:column;align-items:flex-end;gap:4px;margin:6px 0;}
.aivle-msg-a{display:flex;flex-direction:column;align-items:flex-start;gap:4px;margin:6px 0;}
.aivle-msg-label{font-size:12px;color:var(--muted);}
.aivle-bubble-u{max-width:78%;background:var(--primary);color:#fff;padding:12px 16px;border-radius:20px 20px 4px 20px;font-size:15px;line-height:1.6;overflow-wrap:anywhere;word-break:keep-all;}
.aivle-bubble-a{max-width:88%;background:var(--tint2);color:var(--text);padding:14px 18px;border-radius:20px 20px 20px 4px;font-size:15px;line-height:1.7;overflow-wrap:anywhere;word-break:keep-all;}
.aivle-tool{display:block;font-size:12px;color:var(--primary-text);margin-top:6px;}
/* 캘린더 (네이티브 그리드: 셀 = 컨테이너, 칩 = 버튼) */
.aivle-legend{display:flex;gap:14px;font-size:13px;color:var(--text2);flex-wrap:wrap;margin-bottom:10px;}
.aivle-legend span{display:inline-flex;align-items:center;gap:6px;}
.aivle-legend i{width:12px;height:12px;border-radius:4px;display:inline-block;}
.aivle-dow{text-align:center;color:var(--muted);font-size:13px;margin:0;}
[class*="st-key-cell_"],[class*="st-key-cellt_"]{background:#F8FAFC;border-radius:14px;padding:6px 6px 4px;min-height:88px;box-sizing:border-box;}
[class*="st-key-cellt_"]{background:#fff;border:2px solid var(--cal);}
.aivle-daynum{font-size:13px;color:var(--muted);display:block;margin:0 0 2px 2px;}
[class*="st-key-cellt_"] .aivle-daynum{color:var(--cal);font-weight:700;}
[class*="st-key-cell_"] .stButton>button,[class*="st-key-cellt_"] .stButton>button{min-height:24px;padding:0 6px;font-size:11px;border-radius:6px;width:100%;justify-content:flex-start;line-height:1.2;}
[class*="st-key-cell_"] .stButton>button p,[class*="st-key-cellt_"] .stButton>button p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;font-size:11px;}
[class*="st-key-evA_"] button{background:var(--primary)!important;color:#fff!important;border-color:var(--primary)!important;}
[class*="st-key-evC_"] button{background:var(--cal-tint)!important;color:var(--cal-text)!important;border-color:var(--cal-tint)!important;}
[class*="st-key-evP_"] button{background:#fff!important;color:var(--primary-text)!important;border:1px dashed var(--primary)!important;}
[class*="st-key-evOK_"] button{background:var(--primary)!important;color:#fff!important;border-color:var(--primary)!important;}
[class*="st-key-evX_"] button{background:#F1F5F9!important;color:#94A3B8!important;text-decoration:line-through;border-color:#E2E8F0!important;}
[class*="st-key-evD_"] button{background:#E2E8F0!important;color:#64748B!important;border-color:#E2E8F0!important;}
.aivle-more{font-size:11px;color:var(--muted);margin:0 0 0 4px;}
/* 다이얼로그 */
.aivle-dlg-count{font-size:12px;color:var(--muted);}
.aivle-dlg-row{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--tint);}
.aivle-dlg-k{flex:0 0 84px;font-size:12px;color:var(--muted);padding-top:2px;}
.aivle-dlg-v{flex:1 1 auto;min-width:0;font-size:14px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere;}
.aivle-demo-note{font-size:12px;color:var(--warn);background:var(--warn-bg);padding:6px 10px;border-radius:10px;margin:8px 0;}
/* 11/4 시연 전 정리: 업로드·날짜 같은 크기, 버튼 폭, 음성 플레이어 */
.aivle-hint-sm{font-size:12px;color:var(--muted);margin:6px 0 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.st-key-card_upload [data-testid="stWidgetLabel"] p{font-size:15px!important;font-weight:700!important;}
.st-key-card_upload [data-testid="stFileUploaderDropzone"]{min-height:58px;height:58px;padding:6px 14px;box-sizing:border-box;}
.st-key-card_upload [data-testid="stDateInput"] [data-baseweb="input"]{min-height:58px;height:58px;border:1px dashed var(--primary)!important;background:var(--tint2)!important;border-radius:16px!important;}
.st-key-card_upload [data-testid="stDateInput"] input{height:56px;}
[class*="st-key-chip_"],[class*="st-key-chip_"] .stButton,[class*="st-key-chip_"] button{width:100%;}
[class*="st-key-tlink_"],[class*="st-key-tlink_"] .stButton{width:100%;}
[class*="st-key-tlink_"] button{min-height:44px;}
[data-testid="stSidebar"] [class*="st-key-nav_"],[data-testid="stSidebar"] [class*="st-key-nav_"] .stButton,[data-testid="stSidebar"] [class*="st-key-nav_"] button{width:100%;}
.aivle-audio{width:100%;max-width:420px;height:40px;margin:4px 0 8px;display:block;}
/* 사이드바 메뉴: 아이콘 + 왼쪽 정렬 (시안 G) */
[data-testid="stSidebar"] [class*="st-key-nav_"] button{padding:0 14px;gap:10px;}
[data-testid="stSidebar"] [class*="st-key-nav_"] button>div,[data-testid="stSidebar"] [class*="st-key-nav_"] button [data-testid="stMarkdownContainer"]{justify-content:flex-start!important;text-align:left!important;width:100%;}
[data-testid="stSidebar"] [class*="st-key-nav_"] button p{text-align:left!important;font-size:15px;}
[data-testid="stSidebar"] .st-key-nav_assistant button[kind="secondary"] [data-testid="stIconMaterial"]{color:var(--primary);}
[data-testid="stSidebar"] .st-key-nav_tasks button[kind="secondary"] [data-testid="stIconMaterial"]{color:var(--task);}
[data-testid="stSidebar"] .st-key-nav_calendar button[kind="secondary"] [data-testid="stIconMaterial"]{color:var(--cal);}
/* 작성기: 마이크 · 입력 · 전송 한 줄 (시안 G) */
.st-key-mic_box [data-testid="stAudioInput"]>div{border-radius:999px!important;background:var(--tint)!important;min-height:52px;}
.st-key-card_chat [data-testid="stForm"]{padding:0;border:none;}
.st-key-card_chat [data-baseweb="input"]{min-height:52px;}
.st-key-card_chat .stFormSubmitButton>button{width:100%;min-height:52px;}
.st-key-btn_clear button{min-height:34px;font-size:13px;border:none;color:var(--muted);text-decoration:underline;background:transparent;}
/* 카드 아래 여백 */
.st-key-card_meeting,.st-key-card_upload,.st-key-card_chat,.st-key-card_calendar,.st-key-card_upcoming,.st-key-card_sent,.st-key-card_empty,[class*="st-key-task_card_"],[class*="st-key-task_sel_"],[class*="st-key-req_"]{padding:22px 24px 26px!important;}
/* AIVLE 라벨 + 스피커 */
[class*="st-key-ahead_"]{gap:2px!important;margin-top:6px;}
[class*="st-key-ahead_"] .stButton>button{min-height:28px;height:28px;width:28px;padding:0;border:none;background:transparent;color:var(--primary-text);}
[class*="st-key-ahead_"] .stButton>button:hover{background:var(--tint);}
[class*="st-key-ahead_"] [data-testid="stMarkdownContainer"] p{margin:0;}
/* 내 업무 버튼 2x2: 칸을 꽉 채움 */
.st-key-page_tasks [data-testid="stColumn"] .stButton,.st-key-page_tasks [data-testid="stColumn"] .stButton>button{width:100%;}
.st-key-page_tasks [data-testid="stColumn"] .stButton>button{min-height:42px;font-size:13px;padding:0 10px;}
/* 캘린더 머리줄 */
.st-key-cal_head .stButton>button{min-height:40px;height:40px;border-radius:12px;padding:0 14px;}
.st-key-cal_head [class*="st-key-btn_prev"] button,.st-key-cal_head [class*="st-key-btn_next"] button{width:40px;padding:0;}
/* 캘린더 칸: 크기 고정, 업무 칩은 한 줄로 줄어듦, 넘치면 +N */
[class*="st-key-cell_"],[class*="st-key-cellt_"]{height:118px;min-height:118px;overflow:hidden;gap:3px!important;padding:6px 6px 4px;}
[class*="st-key-cell_"] .stButton,[class*="st-key-cellt_"] .stButton{width:100%;min-width:0;}
[class*="st-key-cell_"] .stButton>button,[class*="st-key-cellt_"] .stButton>button{height:22px;min-height:22px;padding:0 6px;min-width:0;overflow:hidden;}
[class*="st-key-cell_"] .stButton>button *,[class*="st-key-cellt_"] .stButton>button *{white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;font-size:11px!important;line-height:22px!important;margin:0!important;}
[class*="st-key-cell_"] [data-testid="stMarkdownContainer"] p,[class*="st-key-cellt_"] [data-testid="stMarkdownContainer"] p{margin:0;}
.aivle-more{font-size:11px;font-weight:700;color:var(--primary-text);margin:0 0 0 4px;line-height:14px;}
/* 다이얼로그 버튼: 위 구분선과 간격, 칸 꽉 채움 */
[data-testid="stDialog"] [data-testid="stHorizontalBlock"]{margin-top:20px;}
[data-testid="stDialog"] [data-testid="stColumn"] [data-testid="stElementContainer"]:has(.stButton),
[data-testid="stDialog"] [data-testid="stColumn"] .stButton,[data-testid="stDialog"] [data-testid="stColumn"] .stButton>button{width:100%!important;}
[data-testid="stDialog"] .stButton>button{min-height:44px;}
/* 내 업무 2x2 / 다가오는 일정 / 캘린더 칩: 칸 꽉 채움 (Streamlit 인라인 폭 덮어쓰기) */
.st-key-page_tasks [data-testid="stColumn"] [data-testid="stElementContainer"]:has(.stButton),
.st-key-page_tasks [data-testid="stColumn"] .stButton,.st-key-page_tasks [data-testid="stColumn"] .stButton>button,
.st-key-card_upcoming [data-testid="stElementContainer"]:has(.stButton),.st-key-card_upcoming .stButton,.st-key-card_upcoming .stButton>button,
.st-key-card_sent [data-testid="stElementContainer"]:has(.stButton),.st-key-card_sent .stButton,.st-key-card_sent .stButton>button,
[class*="st-key-cell_"] [data-testid="stElementContainer"]:has(.stButton),[class*="st-key-cellt_"] [data-testid="stElementContainer"]:has(.stButton){width:100%!important;max-width:100%!important;}
.st-key-card_upcoming .stButton>button,.st-key-card_sent .stButton>button{justify-content:flex-start;}
.aivle-card-title{font-size:18px;font-weight:700;margin:0 0 14px;}
/* 마이크: 동그란 버튼만 보이게 */
.st-key-mic_box{width:56px!important;flex:0 0 56px!important;}
.st-key-mic_box [data-testid="stAudioInput"]{width:56px!important;min-width:56px!important;overflow:hidden!important;border-radius:999px!important;}
.st-key-mic_box [data-testid="stAudioInput"]>div{width:56px!important;min-width:56px!important;height:52px;padding:0!important;justify-content:center!important;overflow:hidden!important;}
/* 11/4 2차: 마이크 동그라미, 대화 머리줄, 회의록 요약 */
.st-key-mic_box{width:56px!important;min-width:56px!important;flex:0 0 56px!important;}
.st-key-mic_box [data-testid="stAudioInput"]{width:56px!important;min-width:56px!important;overflow:visible!important;}
.st-key-mic_box [data-testid="stAudioInput"]>div:not([data-testid="stWidgetLabel"]){width:52px!important;min-width:52px!important;height:52px!important;min-height:52px!important;padding:0!important;margin:0 auto!important;
  border-radius:999px!important;border:none!important;background:var(--primary)!important;display:flex!important;align-items:center!important;justify-content:center!important;overflow:hidden!important;}
.st-key-mic_box [data-testid="stAudioInputWaveformTimeCode"],
.st-key-mic_box div:has(> [data-testid="stAudioInputWaveSurfer"]),
.st-key-mic_box [data-testid="stElementToolbar"]{display:none!important;}
.st-key-mic_box [data-testid="stAudioInput"]>div:not([data-testid="stWidgetLabel"])>div{margin:0!important;padding:0!important;flex:0 0 auto!important;}
.st-key-mic_box [data-testid="stAudioInputActionButton"]{width:52px!important;height:52px!important;color:#fff!important;border-radius:999px!important;}
.st-key-mic_box [data-testid="stAudioInputActionButton"] *{color:#fff!important;}
.st-key-mic_box [data-testid="stAudioInputActionButton"] svg{width:24px;height:24px;}
.st-key-card_chat [data-testid="stHorizontalBlock"]:has(.st-key-mic_box){align-items:center!important;}
.st-key-card_chat .stFormSubmitButton,.st-key-card_chat [data-testid="stElementContainer"]:has(.stFormSubmitButton){width:100%!important;}
.st-key-card_chat .stFormSubmitButton>button{width:100%!important;min-height:52px;border-radius:999px;}
.aivle-pill{display:inline-flex;align-items:center;height:30px;padding:0 12px;border-radius:999px;background:var(--tint);color:var(--primary-text);font-size:13px;font-weight:500;white-space:nowrap;}
.st-key-chat_head,.st-key-sum_head{margin-bottom:6px;}
.st-key-chat_head .stButton>button{min-height:30px;height:30px;padding:0 10px;border:none;background:transparent;color:var(--muted);font-size:13px;}
.st-key-chat_head .stButton>button:hover{background:#FEE2E2;color:#B91C1C;}
.st-key-card_summary{background:#fff;border-radius:24px;padding:22px 24px 26px!important;box-shadow:var(--shadow);box-sizing:border-box;}
.st-key-card_summary textarea{font-size:14px!important;line-height:1.75!important;background:var(--tint2)!important;}
.st-key-card_summary [data-baseweb="textarea"]{border-color:transparent!important;background:var(--tint2)!important;}
.st-key-sum_actions{margin-top:8px;}
.st-key-sum_actions .stButton>button,.st-key-sum_actions .stDownloadButton>button{min-height:44px;border-radius:12px;padding:0 18px;}
.stDownloadButton>button{border-radius:12px;border:1px solid var(--border);background:#fff;color:var(--primary-text);font-size:14px;}
.stDownloadButton>button:hover{border-color:var(--primary);color:var(--primary-text);background:var(--tint2);}
[data-testid="stSidebar"] .st-key-nav_summary button[kind="primary"]{background:var(--primary);color:#fff;font-weight:500;}
[data-testid="stSidebar"] .st-key-nav_summary button[kind="secondary"] [data-testid="stIconMaterial"]{color:var(--primary);}
.st-key-card_upload [data-testid="stDateInput"]{max-width:240px;}
/* 11/4 3차: 캘린더 칸 — 버튼이 툴팁 래퍼 안에 있어 자손 선택자로 강제 */
[class*="st-key-cell_"],[class*="st-key-cellt_"]{display:flex!important;flex-direction:column!important;flex-wrap:nowrap!important;justify-content:flex-start!important;gap:3px!important;height:118px!important;min-height:118px!important;overflow:hidden!important;}
[class*="st-key-cell_"]>*,[class*="st-key-cellt_"]>*{flex:0 0 auto!important;min-height:0!important;margin:0!important;}
[class*="st-key-cell_"] .aivle-daynum,[class*="st-key-cellt_"] .aivle-daynum{display:block;height:18px;line-height:18px;margin:0 0 2px 2px;}
[class*="st-key-cell_"] .stButton,[class*="st-key-cellt_"] .stButton,
[class*="st-key-cell_"] .stButton div,[class*="st-key-cellt_"] .stButton div{width:100%!important;max-width:100%!important;min-width:0!important;}
[class*="st-key-cell_"] .stButton button,[class*="st-key-cellt_"] .stButton button{height:20px!important;min-height:20px!important;max-height:20px!important;padding:0 6px!important;border-radius:6px!important;
  width:100%!important;justify-content:flex-start!important;overflow:hidden!important;line-height:20px!important;}
[class*="st-key-cell_"] .stButton button *,[class*="st-key-cellt_"] .stButton button *{font-size:10.5px!important;line-height:20px!important;white-space:nowrap!important;overflow:hidden!important;text-overflow:ellipsis!important;margin:0!important;text-align:left!important;}
.aivle-more{display:block;font-size:10.5px!important;line-height:14px!important;}
/* 회의록 카드 */
.st-key-meeting_row [data-testid="stMarkdownContainer"] p{margin:0;}
.st-key-meeting_row .stButton button{min-height:44px;border-radius:12px;white-space:nowrap;}
/* AIVLE 라벨 바로 옆 스피커 (같은 줄, 세로 가운데) */
[class*="st-key-ahead_"]{display:flex!important;flex-direction:row!important;align-items:center!important;justify-content:flex-start!important;gap:2px!important;height:28px;margin-top:6px;}
[class*="st-key-ahead_"]>*{flex:0 0 auto!important;width:auto!important;min-width:0!important;margin:0!important;}
[class*="st-key-ahead_"] .stMarkdown,[class*="st-key-ahead_"] [data-testid="stMarkdownContainer"],[class*="st-key-ahead_"] [data-testid="stMarkdownContainer"] p{margin:0!important;padding:0!important;line-height:28px!important;}
[class*="st-key-ahead_"] .aivle-msg-label{display:inline-block;line-height:28px;}
[class*="st-key-ahead_"] .stButton button{width:26px!important;height:26px!important;min-height:26px!important;padding:0!important;margin:0!important;}
[class*="st-key-ahead_"] .stButton button [data-testid="stIconMaterial"]{font-size:18px!important;}
/* 캘린더 날짜: 칸 왼쪽 위에 고정, 칩은 그 아래부터 */
[class*="st-key-cell_"],[class*="st-key-cellt_"]{position:relative!important;padding:26px 6px 4px!important;}
[class*="st-key-cell_"] [data-testid="stElementContainer"]:has(.aivle-daynum),[class*="st-key-cellt_"] [data-testid="stElementContainer"]:has(.aivle-daynum){position:absolute!important;top:5px;left:8px;width:auto!important;height:18px!important;margin:0!important;z-index:1;}
[class*="st-key-cell_"] .aivle-daynum,[class*="st-key-cellt_"] .aivle-daynum{margin:0!important;line-height:18px!important;white-space:nowrap;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# =========================================================
# 2) 공용 저장소 — 앱 안 캘린더 (일정 + 협업·미팅 요청)
#    st.cache_resource 로 만든 dict 를 모든 접속자가 공유한다 (같은 서버 프로세스가 살아 있는 동안).
#    앱이 재시작/재배포되면 초기화되고 기본 일정이 다시 만들어진다.
# =========================================================
def parse_iso(s):
    """'YYYY-MM-DD' → date, 실패하면 None"""
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def store_add(store, **fields):
    """일정 1건 추가 → id. 기본 필드를 채운 뒤 fields 로 덮어쓴다"""
    ev = {"id": uuid.uuid4().hex[:10], "title": "", "date": None, "start_time": None, "end_time": None, "description": "",
          "source": "calendar", "task_id": None, "status": None, "kind": "event", "request_type": None, "subject": None,
          "from": None, "to": [], "message": "", "reason": "", "decided_by": None,
          "created": datetime.now(KST).isoformat(timespec="seconds")}
    ev.update(fields)
    with store["lock"]:
        store["events"][ev["id"]] = ev
        store["version"] += 1
    return ev["id"]


def store_update(store, event_id, **fields):
    with store["lock"]:
        ev = store["events"].get(event_id)
        if not ev:
            return False
        ev.update(fields)
        store["version"] += 1
        return True


def store_get(store, event_id):
    with store["lock"]:
        ev = store["events"].get(event_id)
        return dict(ev) if ev else None


def store_list(store, start_iso="0000-01-01", end_iso="9999-12-31"):
    """기간 내 일정 (날짜·시간 순 복사본)"""
    with store["lock"]:
        items = [dict(e) for e in store["events"].values() if e["date"] and start_iso <= e["date"] <= end_iso]
    return sorted(items, key=lambda e: (e["date"], e.get("start_time") or ""))


def seed_store(store, today_iso):
    """시연용 기본 일정: 오늘 '외부 미팅'(종일), 7일 뒤 '마케팅 일정 점검 회의'(10:00~11:00)"""
    d = parse_iso(today_iso)
    store_add(store, title="외부 미팅", date=d.isoformat(), source="calendar", description=f"{USER_NAME} 외부 미팅 (오늘 회의에 참석하지 못한 이유)")
    store_add(store, title="마케팅 일정 점검 회의", date=(d + timedelta(days=7)).isoformat(), start_time="10:00", end_time="11:00",
              source="calendar", description="신제품 마케팅 전체 일정 점검 (다음 주 회의)")


def new_store(today_iso):
    store = {"lock": threading.Lock(), "events": {}, "version": 0}
    seed_store(store, today_iso)
    return store


def store_reset(store, today_iso):
    with store["lock"]:
        store["events"].clear()
        store["version"] += 1
    seed_store(store, today_iso)


@st.cache_resource(show_spinner=False)
def get_store():
    return new_store(datetime.now(KST).date().isoformat())


STORE = get_store()


# =========================================================
# 3) 상태
# =========================================================
today = datetime.now(KST).date()

DEFAULTS = {
    "page": "assistant",         # assistant / tasks / calendar / requests
    "view_as": USER_NAME,        # 보기 모드: 김 대리(주인) 또는 팀원 이름
    "qp_handled": False,         # 링크(?req=..&as=..) 처리 여부
    "focus_request": None,       # 링크로 열린 요청 id
    "messages": [],              # [{"id","role","content","via","tools":[[tool,status],...],"show_tasks"}]
    "meeting_text": None,
    "meeting_name": None,
    "meeting_date": today.isoformat(),
    "briefing": None,            # {"title","participants","summary","facts"}
    "tasks": [],                 # [{"id","title","detail","requester","due","suggested_due","suggest_reason","event_id","done"}]
    "briefing_key": None,
    "show_uploader": False,
    "selected_task": None,       # 대화의 업무 카드에서 고른 업무 id
    "prefill": None,             # 다른 페이지에서 넘어오며 바로 보낼 문장
    "drafts": {},                # task_id → 초안 텍스트
    "draft_rev": {},             # task_id → 다시 쓴 횟수 (text_area 키 갱신용)
    "draft_task": None,          # 초안 다이얼로그가 열린 업무 id
    "open_event": None,          # 일정 다이얼로그가 열린 일정 id
    "request_form": None,        # 협업·미팅 요청 다이얼로그 내용
    "request_mode": "summary",
    "reject_for": None,          # 거절 이유 입력 중인 요청 id
    "req_status_seen": {},       # 요청 id → 마지막으로 본 상태 (변경 토스트용)
    "pending_actions": [],       # 확인 대기 중인 작업 (이메일/캘린더)
    "dlg_action_id": None,
    "dlg_mode": "summary",
    "emails_sent": 0,
    "last_audio_hash": None,
    "tts_audio": None,
    "tts_autoplay": False,
    "cal_year": today.year,
    "cal_month": today.month,
    "confirm_reset": False,
    "summary_text": None,        # 회의록 요약 (txt 저장 / 메일 발송용)
    "summary_key": None,         # 어떤 회의록으로 만든 요약인지
    "summary_rev": 0,            # 다시 요약할 때 text_area 키 갱신
    "mic_n": 0,                  # 녹음을 처리하면 마이크를 새로 만들어 다시 누를 수 있게
    "notice": None,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


def set_notice(kind, text):
    """사용자에게 보여줄 안내. kind: error(실제 실패) / warning / note(조용한 안내)"""
    st.session_state.notice = (kind, text)


def render_notice():
    """notice 를 한 번 보여주고 지운다. 설정 누락은 조용한 안내, 실제 실패만 빨간 상자"""
    if not st.session_state.notice:
        return
    kind, text = st.session_state.notice
    st.session_state.notice = None
    if kind == "error":
        st.error(text)
    elif kind == "warning":
        st.warning(text)
    else:
        st.markdown(f'<p class="aivle-note">{esc(text)}</p>', unsafe_allow_html=True)


def go(page, **updates):
    """페이지 이동 + 상태 갱신 후 rerun"""
    st.session_state.page = page
    st.session_state.tts_autoplay = False                # 페이지를 옮기면 읽던 음성은 멈춤
    for k, v in updates.items():
        st.session_state[k] = v
    st.rerun()


# =========================================================
# 4) 도구 함수 (순수 함수 중심)
# =========================================================
def esc(text):
    """HTML 이스케이프 + 줄바꿈 유지"""
    return html.escape(str(text or "")).replace("\n", "<br>")


def fmt_short(iso):
    """2026-11-13 → '11.13'"""
    d = parse_iso(iso)
    return f"{d.month:02d}.{d.day:02d}" if d else "미정"


def fmt_kor(iso):
    """2026-11-13 → '11/13 (금)'"""
    d = parse_iso(iso)
    return f"{d.month}/{d.day} ({WEEKDAY_KO[d.weekday()]})" if d else "미정"


def fmt_kor_day(iso):
    """2026-11-13 → '11월 13일 (금)'"""
    d = parse_iso(iso)
    return f"{d.month}월 {d.day}일 ({WEEKDAY_KO[d.weekday()]})" if d else "미정"


def fmt_long_kor(iso):
    """2026-11-13 → '11월 13일 금요일'"""
    d = parse_iso(iso)
    return f"{d.month}월 {d.day}일 {WEEKDAY_KO[d.weekday()]}요일" if d else "미정"


def fmt_header_date(d):
    """2026.11.04 WED"""
    return f"{d.year}.{d.month:02d}.{d.day:02d} {WEEKDAY_EN[d.weekday()]}"


def fmt_when(ev):
    """일정의 날짜·시간 표시: '11월 11일 (수) 10:00~11:00' 또는 '... 종일'"""
    base = fmt_kor_day(ev.get("date"))
    if ev.get("start_time"):
        return f"{base} {ev['start_time']}~{ev.get('end_time') or ''}".rstrip("~")
    return f"{base} 종일"


def end_time_of(start_hhmm, minutes):
    """'10:00' + 60분 → '11:00'"""
    h, m = [int(x) for x in start_hhmm.split(":")]
    total = (h * 60 + m + int(minutes)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def trim_history(messages, max_turns=MAX_TURNS):
    """사용자 발화 기준으로 최근 max_turns 턴만 남긴다"""
    user_idx = [i for i, m in enumerate(messages) if m["role"] == "user"]
    if len(user_idx) <= max_turns:
        return messages
    return messages[user_idx[-max_turns]:]


def count_turns(messages):
    return sum(1 for m in messages if m["role"] == "user")


def tool_lines(tools):
    """[[tool, status], ...] → 한국어 결과 문구 목록 (같은 결과는 건수로 합침)"""
    counts = {}
    for item in tools or []:
        key = (item[0], item[1])
        counts[key] = counts.get(key, 0) + 1
    lines = []
    for key, n in counts.items():
        label = TOOL_LABELS.get(key, f"{key[0]} {key[1]}")
        if "{n}" in label:
            lines.append(label.format(n=n))
        else:
            lines.append(label if n == 1 else f"{label} ×{n}")
    return lines


def mentions_tasks(user_text, answer, tasks):
    """답변이 업무에 관한 것인지 (업무 카드를 붙일지) 판단"""
    if not tasks:
        return False
    text = (user_text or "")
    if any(k in text for k in ("업무", "할 일", "할일", "일정 등록", "마감", "배정")):
        return True
    return sum(1 for t in tasks if t["title"][:5] and t["title"][:5] in (answer or "")) >= 2


def decode_text(raw):
    """업로드 파일 디코딩 (utf-8 → cp949)"""
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", errors="ignore")


def strip_for_speech(text):
    """TTS 용으로 마크다운 기호 제거"""
    for ch in ["*", "#", "`", "_"]:
        text = text.replace(ch, "")
    for ch in [">", "- "]:
        text = text.replace(ch, " ")
    return " ".join(text.split())[:600]


# ---- 단계 표시 / 설정 점검 ----
def compute_steps(has_meeting, registered_any, emailed_any):
    """(현재 단계, 끝난 단계 집합). ① 회의록 → ② 업무·일정 → ③ 부탁하기"""
    done = set()
    if has_meeting:
        done.add(1)
    if registered_any or emailed_any:
        done.add(2)
    if emailed_any:
        done.add(3)
    current = 1 if not has_meeting else (2 if 2 not in done else 3)
    return current, done


def stepper_html(current, done, labels=STEP_LABELS):
    parts = ['<div class="aivle-steps">']
    for i, label in enumerate(labels, 1):
        cls = "aivle-step" + (" aivle-step-now" if i == current else "") + (" aivle-step-done" if i in done and i != current else "")
        mark = "✓" if i in done else str(i)
        parts.append(f'<span class="{cls}"><i>{mark}</i>{html.escape(label)}</span>')
    parts.append("</div>")
    return "".join(parts)


def missing_secrets(openai_key, gmail_address, gmail_password):
    """빠진 Secrets 키 이름만 돌려준다 (값은 절대 다루지 않음)"""
    missing = []
    if not openai_key:
        missing.append("OPENAI_API_KEY")
    if not gmail_address:
        missing.append("GMAIL_ADDRESS")
    if not gmail_password:
        missing.append("GMAIL_APP_PASSWORD")
    return missing


# ---- 주소록 / 데모 메일 ----
def resolve_recipient(to, contacts, my_email):
    """'팀장님' / 'teamlead@...' / 'me' → (표시 이름, 주소). 모르면 김 대리 본인"""
    raw = (to or "").strip()
    key = raw.replace("님", "").replace(" ", "")
    for name, email in contacts:
        if key and (key == name.replace(" ", "") or raw.lower() == (email or "").lower()):
            return name, email
    if "@" in raw:
        return raw, raw
    return USER_NAME, my_email


def demo_envelope(to_label, to_email, subject, body, my_email):
    """데모 발송: 실제 수신자는 항상 my_email. 제목·본문에 원래 받는 사람을 밝힌다"""
    return (my_email,
            f"[{APP_NAME} 데모 → {to_label}] {subject}",
            f"(데모: 원래 받는 사람 {to_label} <{to_email}>)\n\n{body}")


def send_email(to, subject, body):
    """교안 send_email 과 동일 (Gmail SMTP). 실제 주소로 그대로 보낸다"""
    sender = GMAIL_ADDRESS
    password = GMAIL_APP_PASSWORD
    if not (sender and password):
        return {"status": "failed", "error": "GMAIL_ADDRESS / GMAIL_APP_PASSWORD 가 설정되지 않았습니다."}

    # 메일 구성 (본문, 제목, 발신자, 수신자)
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to

    # 메일 보내기 (with 구문: 오류가 나도 연결이 닫힘)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls()
            s.login(sender, password)
            s.sendmail(sender, to, msg.as_string())
        return {"status": "success"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def is_email(addr):
    """간단한 이메일 형식 검사"""
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", (addr or "").strip()))


def send_demo_email(to_label, to_email, subject, body):
    """모든 메일을 MY_EMAIL 로 보내되 원래 받는 사람을 표시"""
    actual_to, subject2, body2 = demo_envelope(to_label, to_email, subject, body, MY_EMAIL)
    return send_email(actual_to, subject2, body2)


# ---- 캘린더 표시 ----
def events_by_date(events):
    grouped = {}
    for ev in events:
        grouped.setdefault(ev["date"], []).append(ev)
    return grouped


def month_range(year, month):
    last_day = cal_lib.monthrange(year, month)[1]
    return date(year, month, 1).isoformat(), date(year, month, last_day).isoformat()


def shift_month(year, month, delta):
    m = month + delta
    y = year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return y, m


def build_month_cells(year, month, grouped, today_iso, max_chips=3):
    """월간 그리드 자료 (월요일 시작). 주 → 7칸, 빈칸은 None"""
    weeks = []
    for week in cal_lib.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(None)
                continue
            iso = f"{year:04d}-{month:02d}-{day:02d}"
            evs = grouped.get(iso, [])
            row.append({"day": day, "iso": iso, "is_today": iso == today_iso,
                        "chips": evs[:max_chips], "more": max(0, len(evs) - max_chips)})
        weeks.append(row)
    return weeks


def chip_style(ev):
    """칩 색: A(AIVLE 업무) C(캘린더 일정) P(요청 대기) OK(요청 확정) X(거절) D(완료)"""
    if ev.get("kind") == "request":
        return {"accepted": "OK", "rejected": "X"}.get(ev.get("status"), "P")
    if ev.get("status") == "done":
        return "D"
    return "A" if ev.get("source") == "able" else "C"


def chip_label(ev, width=18):
    style = chip_style(ev)
    title = ev.get("subject") if ev.get("kind") == "request" else ev.get("title", "")
    title = title or ""
    prefix = {"D": "✓ ", "P": "대기 ", "OK": "확정 ", "X": "거절 "}.get(style, "")
    text = prefix + title
    return text if len(text) <= width else text[: width - 1] + "…"


def find_existing_event(title, date_iso, events):
    """같은 제목 + 같은 날짜 일정이 이미 있으면 반환 (중복 등록 방지)"""
    key = (title or "").strip()
    for ev in events:
        if ev["date"] == date_iso and (ev["title"] or "").strip() == key and ev.get("kind") != "request":
            return ev
    return None


# ---- 협업·미팅 요청 ----
def request_title(request_type, subject, status):
    short = "미팅" if "미팅" in (request_type or "") else "협업"
    if status == "accepted":
        return f"[{short} 확정] {subject}"
    if status == "rejected":
        return f"[거절됨] {subject}"
    return f"[{request_type}] {subject} — 대기"


def apply_decision(event, decision, by, reason=""):
    """수락/거절 → 일정에 반영할 필드. 거절은 이유가 필수"""
    reason = (reason or "").strip()
    if decision not in ("accepted", "rejected"):
        raise ValueError("알 수 없는 결정입니다.")
    if decision == "rejected" and not reason:
        raise ValueError("거절 이유를 입력해 주세요.")
    return {"status": decision, "decided_by": by, "reason": reason if decision == "rejected" else "",
            "title": request_title(event.get("request_type"), event.get("subject"), decision)}


def request_message(task, event, meeting_title):
    """요청 메시지 기본 문구 (AIVLE 초안, 수정 가능)"""
    if task:
        due = fmt_kor_day(task["due"]) if task.get("due") else f"미정 (제안 {fmt_kor_day(task.get('suggested_due'))})"
        return (f"안녕하세요, {USER_NAME}입니다.\n'{task['title']}' 업무 관련해 잠깐 시간을 내어 주실 수 있을까요?\n"
                f"- 내용: {task['detail']}\n- 요청: {task['requester']} · 마감: {due}\n"
                f"- 배경: 「{meeting_title or '회의'}」 회의에서 배정된 업무입니다.\n"
                "가능한 시간대를 알려 주시면 맞추겠습니다. 감사합니다.")
    title = event.get("title") if event else "일정"
    return (f"안녕하세요, {USER_NAME}입니다.\n'{title}' 일정과 관련해 함께 논의할 시간을 요청드립니다.\n"
            "가능한 시간대를 알려 주시면 맞추겠습니다. 감사합니다.")


def request_link(event_id, name):
    return f"{APP_URL}/?req={event_id}&as={quote(name)}" if APP_URL else ""


# ---- 업무 ----
def find_task(task_id):
    for t in st.session_state.tasks:
        if t["id"] == task_id:
            return t
    return None


def match_task_by_title(title):
    """모델이 만든 일정 제목과 업무 제목이 겹치면 그 업무로 연결"""
    key = (title or "").replace(" ", "")
    for t in st.session_state.tasks:
        tk = t["title"].replace(" ", "")
        if tk and (tk in key or key in tk):
            return t
    return None


def task_status(t):
    """todo(추가 전) / scheduled(추가됨) / done(완료)"""
    if t.get("done"):
        return "done"
    return "scheduled" if t.get("event_id") else "todo"


def task_description(t):
    return f"{t['detail']}\n요청: {t['requester']}\n출처: {st.session_state.meeting_name or '회의록'}"


def task_due_label(t):
    """'마감 11월 13일 (금)' 또는 '마감 미정 · AIVLE 제안 11월 9일 (월)'"""
    if t.get("due"):
        return "마감 " + fmt_kor_day(t["due"])
    return f"마감 미정 · {APP_NAME} 제안 {fmt_kor_day(t.get('suggested_due'))}"


def mark_task_done(t, done=True):
    """업무 완료 표시 (캘린더 일정에도 저장 → 새로고침 후에도 유지)"""
    t["done"] = done
    if t.get("event_id"):
        store_update(STORE, t["event_id"], status="done" if done else None)


def restore_task_statuses():
    """저장소의 AIVLE 일정에서 업무의 등록/완료 상태를 되살린다 (다른 기기·새 세션에서도 유지)"""
    if not st.session_state.tasks:
        return
    able = [e for e in store_list(STORE) if e.get("source") == "able"]
    for t in st.session_state.tasks:
        ev = next((e for e in able if e.get("task_id") == t["id"] and e["title"].strip() == t["title"].strip()), None)
        if ev:
            t["event_id"], t["due"] = ev["id"], ev["date"]
            t["done"] = ev.get("status") == "done"
        elif t.get("event_id") and not store_get(STORE, t["event_id"]):
            t["event_id"] = None            # 저장소가 초기화된 경우


# ---- 대화 메시지 / 확인 대기 작업 ----
def new_message(role, content, via="text", tools=None, show_tasks=False):
    return {"id": uuid.uuid4().hex[:8], "role": role, "content": content, "via": via, "tools": tools or [], "show_tasks": show_tasks}


def find_message(msg_id):
    for m in st.session_state.messages:
        if m["id"] == msg_id:
            return m
    return None


def queue_pending(tool_name, args, task_id=None, msg_id=None):
    """send_email / add_calendar_event 는 바로 실행하지 않고 확인 대기열에 넣는다"""
    args = dict(args or {})
    if tool_name == "send_email":
        label, email = resolve_recipient(args.get("to"), CONTACTS, MY_EMAIL)
        args["to_label"], args["to_email"] = label, email
        kind = "email"
    else:
        kind = "calendar"
        if not task_id:
            matched = match_task_by_title(args.get("title"))
            task_id = matched["id"] if matched else None
    action = {"id": uuid.uuid4().hex[:8], "type": kind, "tool": tool_name, "args": args,
              "task_id": task_id, "msg_id": msg_id}
    st.session_state.pending_actions.append(action)
    return action


def queue_task(t):
    """업무 → 캘린더 추가 대기열 (마감 미정이면 제안 날짜를 기본값으로)"""
    return queue_pending("add_calendar_event",
                         {"title": t["title"], "date": t["due"] or t.get("suggested_due") or (today + timedelta(days=7)).isoformat(),
                          "description": task_description(t)},
                         task_id=t["id"])


def remove_pending(action_id):
    st.session_state.pending_actions = [a for a in st.session_state.pending_actions if a["id"] != action_id]


def current_action():
    return st.session_state.pending_actions[0] if st.session_state.pending_actions else None


def update_tool_status(action, status):
    """답변에 붙은 '확인 대기' 결과 줄을 done / cancelled 로 바꾼다"""
    m = find_message(action.get("msg_id")) if action.get("msg_id") else None
    if not m:
        return
    for item in m["tools"]:
        if item[0] == action["tool"] and item[1] == "waiting":
            item[1] = status
            break


def append_assistant(content, tools=None, speak_it=False, show_tasks=False):   # 음성은 스피커 버튼으로만
    st.session_state.messages.append(new_message("assistant", content, tools=tools, show_tasks=show_tasks))
    st.session_state.messages = trim_history(st.session_state.messages)
    if speak_it:
        speak(content)


# =========================================================
# 5) LLM
# =========================================================
# ---- (a) 회의록 분석: JSON 스키마 구조화 출력 ----
BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "meeting_title": {"type": "string", "description": "회의 주제 (20자 이내)"},
        "participants": {"type": "array", "items": {"type": "string"}, "description": "발언한 참석자"},
        "summary": {"type": "string", "description": "김 대리가 알아야 할 결정 사항 중심 2~3문장 요약"},
        "key_facts": {"type": "array", "items": {"type": "string"}, "description": "핵심 사실 4~6개, 각 20자 이내"},
        "tasks": {
            "type": "array",
            "description": "김 대리에게 배정된 업무만",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "업무 이름 (15자 이내)"},
                    "detail": {"type": "string", "description": "세부 요구사항 한 줄 (40자 이내)"},
                    "requester": {"type": "string", "description": "업무를 지시한 사람 (예: 팀장)"},
                    "due": {"type": ["string", "null"], "description": "회의에서 언급된 마감을 회의 날짜 기준 YYYY-MM-DD 로 환산. 언급 없으면 null"},
                    "due_text": {"type": ["string", "null"], "description": "마감 원문 표현 (예: 다음 주까지). 없으면 null"},
                    "suggested_due": {"type": ["string", "null"], "description": "due 가 null 일 때만, 회의 맥락을 근거로 제안하는 YYYY-MM-DD. due 가 있으면 null"},
                    "suggest_reason": {"type": ["string", "null"], "description": "제안 이유 한 줄 (25자 이내). due 가 있으면 null"},
                },
                "required": ["title", "detail", "requester", "due", "due_text", "suggested_due", "suggest_reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["meeting_title", "participants", "summary", "key_facts", "tasks"],
    "additionalProperties": False,
}


def extract_briefing(meeting_text, meeting_date):
    """회의록 → (브리핑 dict, 업무 list). LLM 한 번 호출"""
    wd = WEEKDAY_KO[meeting_date.weekday()]
    system = f"""당신은 회의록을 분석하는 비서 '{APP_NAME}'입니다. 회의록에서 {USER_NAME}에게 필요한 정보를 JSON 으로 추출합니다.
회의 날짜: {meeting_date.isoformat()} ({wd}요일)
규칙:
- tasks 에는 {USER_NAME}(김대리)에게 배정된 업무만 넣습니다. 다른 사람 업무는 제외합니다.
- 상대 날짜 환산: "다음 주까지" → 다음 주 금요일, "이번 주까지" → 이번 주 금요일, "다음 달 초" → 다음 달 5일, "N일 후" → 회의 날짜 + N일. 결과가 주말이면 직전 금요일로.
- 회의록에서 해당 업무의 마감 표현(예: "다음 주까지 받으면 좋겠습니다")을 찾으면 due_text 에 그 표현의 핵심("다음 주까지")을 그대로 적습니다. 업무 하나에 대한 마감 언급이 다른 문장에 떨어져 있어도 연결해서 찾습니다.
- 마감이 언급되지 않은 업무는 due 를 null 로 두고, 회의 맥락(출시 시점, 다른 업무와의 선후 관계, 다음 회의 등)을 근거로 suggested_due 와 한 줄 이유를 제안합니다. 제안 날짜는 회의 날짜 이후 평일이어야 합니다.
- summary 는 {USER_NAME} 관점에서 알아야 할 결정 사항 중심으로 씁니다."""
    response = client.responses.create(
        model=LLM_MODEL,
        input=[{"role": "system", "content": system},
               {"role": "user", "content": f"[회의록]\n{meeting_text}"}],
        text={"format": {"type": "json_schema", "name": "meeting_brief", "schema": BRIEF_SCHEMA, "strict": True}},
        temperature=0,                                   # 같은 회의록이면 같은 결과가 나오도록
    )
    data = json.loads(response.output_text)

    # 날짜는 LLM 에 맡기지 않고 파이썬 규칙으로 다시 계산 (요일 착오 방지)
    def to_weekday(d):                       # 주말이면 직전 금요일
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d

    def add_bdays(d, n):                     # 영업일 n 일 뒤
        while n > 0:
            d += timedelta(days=1)
            if d.weekday() < 5:
                n -= 1
        return d

    def resolve_due(text, llm_due):
        text = text or ""
        monday_next = meeting_date + timedelta(days=7 - meeting_date.weekday())
        if "다음 주" in text or "다음주" in text:
            return monday_next + timedelta(days=4), "다음 주 금요일"
        if "이번 주" in text or "이번주" in text:
            return meeting_date + timedelta(days=4 - meeting_date.weekday()), "이번 주 금요일"
        if "다음 달" in text or "다음달" in text:
            first = (meeting_date.replace(day=1) + timedelta(days=32)).replace(day=1)
            return to_weekday(first + timedelta(days=4)), "다음 달 초"
        if llm_due and monday_next <= llm_due <= monday_next + timedelta(days=6):
            return monday_next + timedelta(days=4), text or "다음 주 금요일"   # 다음 주 마감은 금요일로 통일
        return (to_weekday(llm_due), text) if llm_due else (None, text)

    tasks = []
    undated_n = 0
    for i, t in enumerate(data.get("tasks", [])):
        due, due_text = resolve_due(t.get("due_text"), parse_iso(t.get("due")))
        suggested, reason = None, None
        if due is None:
            suggested = add_bdays(meeting_date, 5 + undated_n)     # 다음 주 같은 요일부터 하루씩
            undated_n += 1
            reason = "회의에서 마감이 정해지지 않아 회의 후 약 1주(영업일 기준)로 제안해요"
        t["due_text"] = due_text
        tasks.append({
            "id": f"t{i + 1}",
            "title": (t.get("title") or "").strip() or f"업무 {i + 1}",
            "detail": (t.get("detail") or "").strip(),
            "requester": (t.get("requester") or "").strip() or "미상",
            "due": due.isoformat() if due else None,
            "due_text": t.get("due_text"),
            "suggested_due": suggested.isoformat() if suggested else None,
            "suggest_reason": reason or "",
            "event_id": None,
            "done": False,
        })
    briefing = {
        "title": data.get("meeting_title") or "회의",
        "participants": data.get("participants") or [],
        "summary": data.get("summary") or "",
        "facts": data.get("key_facts") or [],
    }
    return briefing, tasks


def load_meeting(text, name, meeting_date, key):
    """회의록을 상태에 저장하고 분석. 분석이 끝나면 대화에 브리핑을 올리고 읽어 준다"""
    st.session_state.meeting_text = text
    st.session_state.meeting_name = name
    st.session_state.meeting_date = meeting_date.isoformat()
    st.session_state.briefing_key = key
    st.session_state.briefing, st.session_state.tasks = None, []
    st.session_state.selected_task = None
    st.session_state.drafts, st.session_state.draft_rev = {}, {}
    st.session_state.summary_text, st.session_state.summary_key = None, None
    st.session_state.summary_rev += 1
    st.session_state.show_uploader = False
    if client is None:
        set_notice("note", "OPENAI_API_KEY 가 없어 회의록 분석은 건너뛰었어요. 회의록 원문은 기억해 둘게요. (사이드바 '설정 안내' 참고)")
        return False
    try:
        with st.spinner("회의록을 읽고 요약하는 중…"), ThreadPoolExecutor(max_workers=1) as pool:
            summary_job = pool.submit(generate_summary, text, meeting_date.isoformat())   # 요약은 옆에서 동시에
            briefing, tasks = extract_briefing(text, meeting_date)
            try:
                summary = summary_job.result()
            except Exception:
                summary = None                                    # 요약 탭에서 다시 시도
        st.session_state.briefing, st.session_state.tasks = briefing, tasks
        st.session_state.summary_text = summary
        st.session_state.summary_key = key if summary else None
        st.session_state.summary_rev += 1
        restore_task_statuses()
        st.toast(f"회의록을 불러왔어요 · {briefing['title']}")
        return True
    except Exception as e:
        set_notice("error", f"회의록 분석에 실패했어요: {e} — 잠시 후 '다시 분석'을 눌러 주세요.")
        return False


# ---- (a2) 회의록 요약 (txt 저장 / 메일 발송용) ----
SUMMARY_PROMPT = f"""당신은 마케팅팀 '{USER_NAME}'의 음성인식 AI 개인비서 '에이블'입니다.
{USER_NAME}가 요청한 업무를 최선을 다해 처리합니다.

[{USER_NAME} 정보]
- 소속: 마케팅팀 (Marketing Data Analyst)
- 담당: 마케팅 전략 분석, 콘텐츠 기획, 데이터 기반 의사결정 지원
- 잦은 외부 미팅으로 회의에 참석하지 못하는 경우가 많습니다.

[에이블의 담당 업무]
1. 회의록 분석 및 요약
2. {USER_NAME}에게 배정된 업무 지시사항 추출
3. {USER_NAME}의 다양한 질문에 대한 응답
4. {USER_NAME}가 요청할 때만 이메일 발송

[답변 원칙]
1. 정중한 존댓말로 답합니다.
2. 근거가 없는 내용은 지어내지 않고, 정해지지 않은 사항은 '미정'이라고 표시합니다.
3. 금액, 날짜, 기간, 수량, 비율 같은 숫자 정보는 원문 그대로 빠짐없이 적습니다.
4. 결정된 내용뿐 아니라 그렇게 결정한 이유와 근거도 함께 적습니다.

[회의록 요약 원칙]
회의록 요약을 요청받으면, 회의에 참석하지 못한 {USER_NAME}가 이것만 읽고 바로 업무를 시작할 수 있도록
중요한 정보를 빠뜨리지 않고 자세하게 다음 순서로 정리합니다. 회의에서 다루지 않은 항목은 생략합니다.

1. 회의 개요: 회의 주제와 목적을 한두 문장으로 정리
2. {USER_NAME}에게 배정된 업무 (가장 자세하게, 하나도 빠짐없이)
   - 업무마다 업무 내용, 배경과 목적, 구체적 범위(채널, 대상, 참고 사례 등), 결과물 형태,
     마감일, 요청한 사람, 회의에서 강조된 점, 바로 시작할 첫 행동
   - 마감일은 업무마다 회의록에서 그 업무에 대해 직접 언급된 것만 적고, 없으면 '미정'으로 적기
   - 배정된 업무가 없으면 '배정된 업무 없음'이라고 적기
3. 마케팅 주요 논의 내용 (항목별 결정 사항과 이유)
   - 목표와 성과 지표, 타겟 고객, 전략과 방향, 채널별 활용 계획과 선택 이유,
     콘텐츠 방향, 경쟁사 및 시장 동향, 예산, 일정, 프로모션과 이벤트, 협업 사항
4. 다른 팀원의 업무
5. 정리: 결정된 사항, 미정 사항, 다음 일정
6. 참석자별 주요 발언 (마지막에 간략하게)

[출력 형식]
txt 파일로 저장하고 메일 본문으로 보낼 문서입니다. 마크다운 기호(#, *, **, 표)를 쓰지 말고,
'1. 회의 개요' 같은 번호 제목과 '-' 목록, 들여쓰기만 사용합니다."""


def generate_summary(meeting_text, meeting_date):
    """회의록 → 김 대리용 상세 요약 텍스트 (LLM)"""
    user = f"회의 날짜: {meeting_date}\n\n[회의록]\n{meeting_text}\n\n위 회의록을 요약 원칙에 따라 정리해 주세요."
    response = client.responses.create(model=LLM_MODEL, temperature=0,
                                       input=[{"role": "system", "content": SUMMARY_PROMPT}, {"role": "user", "content": user}])
    return (response.output_text or "").strip()


# ---- (b) 업무 초안 작성 ----
def generate_draft(task):
    """회의 맥락 + 업무 → 바로 다듬어 쓸 수 있는 초안 (LLM)"""
    system = (f"당신은 {USER_NAME}의 비서 '{APP_NAME}'입니다. 업무를 설명하지 말고, 그 업무의 결과물 자체의 초안을 한국어로 작성합니다. "
              "예: 'SNS 콘텐츠 초안'이면 실제 게시물 문구 3안(기능 강조형, 후기형, 숏폼 영상 대본), "
              "'경쟁사 분석 보고서'면 보고서 목차와 각 항목에 채울 내용·조사 방법, "
              "'인플루언서 후보 조사'면 선정 기준표와 후보 조사 양식(플랫폼, 팔로워 규모, 협업 형태, 예상 비용 칸). "
              "회의록의 결정 사항(출시 시점, 채널, 예산, 콘텐츠 방향)을 반영하고, 회의록에 없는 회사·채널·수치·실명은 절대 지어내지 말고(예: 회의록에 A사만 나오면 B사, C사를 만들지 않음) 빈칸은 [확인 필요]로 둡니다. "
              "마크다운 기호(#, *, **) 없이 제목 한 줄, 번호 목록, 짧은 문단으로 600자 안팎.")
    user = (f"[업무] {task['title']}\n세부: {task['detail']}\n요청: {task['requester']}\n마감: {task.get('due') or task.get('suggested_due')}\n\n"
            f"[회의록]\n{st.session_state.meeting_text or '(회의록 없음)'}")
    response = client.responses.create(model=LLM_MODEL, input=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return (response.output_text or "").strip()


# ---- (c) 대화용 도구 정의 (Responses API function tools, 교안과 같은 형식) ----
def address_book_text():
    return ", ".join(f"{name} <{email}>" for name, email in CONTACTS)


TOOLS = [
    {
        "type": "function",
        "name": "send_email",
        "description": (f"이메일을 발송합니다. {USER_NAME}가 '메일로 보내줘'처럼 명시적으로 요청할 때만 사용합니다. 실제 발송은 사용자 확인 후 이루어집니다. "
                        f"to 에는 팀 주소록의 이름(김 대리, 팀장, 박과장, 이과장, 최대리) 또는 이메일 주소를 넣습니다. 주소록: {address_book_text()}"),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "받는 사람. 주소록 이름(예: '팀장') 또는 이메일. 수신자를 말하지 않으면 '김 대리'"},
                "subject": {"type": "string", "description": "이메일 제목. 예: '[회의 요약] 신제품 출시 마케팅 전략'"},
                "body": {"type": "string", "description": "이메일 본문. 인사말, 핵심 요약, 업무 목록(마감 포함), 마무리로 구성한 완성된 한국어 메일"},
            },
            "required": ["to", "subject", "body"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "add_calendar_event",
        "description": "업무 마감 등 일정을 AIVLE 캘린더에 종일 일정으로 등록합니다. 업무 하나당 한 번 호출합니다. 실제 등록은 사용자 확인 후 이루어집니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "일정 제목. 예: '경쟁사 마케팅 분석 보고서 마감'"},
                "date": {"type": "string", "description": "날짜 YYYY-MM-DD"},
                "description": {"type": "string", "description": "일정 설명 (업무 세부 내용, 요청자)"},
            },
            "required": ["title", "date", "description"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "list_events",
        "description": "기간 내 캘린더 일정(업무 마감, 회의, 협업·미팅 요청 상태)을 조회합니다. 일정 관련 질문에 답하기 전에 호출합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "조회 시작일 YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "조회 종료일 YYYY-MM-DD (포함)"},
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def tool_list_events(start_date, end_date):
    """list_events 도구 실행: 결과를 모델에 다시 전달"""
    s, e = parse_iso(start_date), parse_iso(end_date)
    if not (s and e):
        return {"status": "failed", "error": "날짜 형식은 YYYY-MM-DD 여야 합니다."}
    if e < s:
        s, e = e, s
    items = []
    for ev in store_list(STORE, s.isoformat(), e.isoformat()):
        d = parse_iso(ev["date"])
        items.append({"date": ev["date"], "weekday": WEEKDAY_KO[d.weekday()] if d else "", "time": ev.get("start_time") or "종일",
                      "title": ev["title"], "source": ev.get("source"), "status": ev.get("status"),
                      "to": ev.get("to") if ev.get("kind") == "request" else None})
    return {"status": "success", "start_date": s.isoformat(), "end_date": e.isoformat(), "count": len(items), "events": items}


def build_system_prompt():
    tasks_brief = [{k: t.get(k) for k in ("id", "title", "detail", "requester", "due", "suggested_due", "suggest_reason", "event_id", "done")}
                   for t in st.session_state.tasks]
    meeting = st.session_state.meeting_text
    lines = [
        f"당신은 '{APP_NAME}'입니다. 마케팅팀 {USER_NAME}의 개인 비서로, {USER_NAME}가 놓친 회의 내용을 정리하고 업무·일정·메일을 대신 처리합니다. "
        f"사용자가 음성으로 '에이블'이라고 부르면 그것은 {APP_NAME}의 한국어 발음이며 당신을 부르는 말입니다. 스스로를 소개할 때는 {APP_NAME}이라고 합니다.",
        "말투: 간결한 한국어 존댓말. 답변은 2~4문장. 음성으로 읽히므로 마크다운, 이모지, 특수기호 없이 자연스러운 문장으로 말합니다. 여러 항목은 '첫째, 둘째'처럼 이어 말합니다.",
        f"오늘: {today.isoformat()} ({WEEKDAY_KO[today.weekday()]}요일). "
        f"이번 주 = {(today - timedelta(days=today.weekday())).isoformat()} ~ {(today + timedelta(days=6 - today.weekday())).isoformat()}, "
        f"다음 주 = {(today + timedelta(days=7 - today.weekday())).isoformat()} ~ {(today + timedelta(days=13 - today.weekday())).isoformat()}. "
        "날짜를 말할 때는 이 범위로 이번 주/다음 주를 판단하고, list_events 결과의 weekday 값을 그대로 씁니다. 일정을 물으면 범위를 이번 주와 다음 주까지 넉넉히 조회합니다.",
        "회의록이 있으면 반드시 회의록 내용에 근거해 답하고, 회의록에 없는 내용은 추측하지 말고 없다고 말합니다. 회의록이 없으면 화면 위의 '회의록 파일(.txt) 올리기'에서 파일을 올려 달라고 한 문장으로 안내합니다.",
        f"팀 주소록: {address_book_text()}. '팀장님께 보내줘'처럼 이름으로 말하면 그 사람을 to 로 씁니다.",
        "도구 사용 규칙:",
        "- send_email: 사용자가 '메일로 보내줘', '이메일로 정리해줘'처럼 명시적으로 요청할 때만 호출합니다. 요약만 원하면 호출하지 않습니다. 수신자를 말하지 않으면 to 에 '김 대리' 를 넣습니다.",
        "- add_calendar_event: 업무나 마감을 캘린더에 넣어 달라고 할 때 호출합니다. 업무마다 한 번씩 호출하고, due 가 없는 업무는 suggested_due 를 쓰며 그 사실을 답변에서 알립니다. event_id 가 이미 있는 업무는 다시 등록하지 않습니다.",
        "- list_events: 일정을 물으면 먼저 호출하고, 그 결과에 있는 일정만 말합니다. 협업·미팅 요청은 status(pending 대기 / accepted 확정 / rejected 거절)를 함께 말합니다.",
        "- 도구 결과가 pending_confirmation 이면 메일은 '메일 초안을 준비했어요. 확인 창에서 보내기를 눌러 주세요', 캘린더는 '일정을 준비했어요. 확인 창에서 추가를 눌러 주세요'처럼 짧게 안내합니다. 실제로 보냈다거나 등록했다고 말하지 마세요.",
        "",
        f"[회의 정보] 회의 날짜: {st.session_state.meeting_date} / 파일: {st.session_state.meeting_name or '없음'}",
        f"[{USER_NAME}의 업무 목록 JSON]\n{json.dumps(tasks_brief, ensure_ascii=False)}",
        f"[회의록 원문]\n{meeting if meeting else '(아직 업로드되지 않았습니다)'}",
    ]
    return "\n".join(lines)


def run_able(assistant_msg_id):
    """대화 1턴 처리. list_events 는 바로 실행해 결과를 모델에 돌려주고,
    send_email / add_calendar_event 는 확인 대기열에 넣는다. (답변, [[도구, 상태], ...]) 반환"""
    input_items = [{"role": "system", "content": build_system_prompt()}]
    input_items += [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]
    statuses = []
    tool_choice = "auto"
    response = None

    for _ in range(3):                                   # 도구 호출 → 결과 전달 → 최종 답변 (최대 3회 반복)
        response = client.responses.create(model=LLM_MODEL, input=input_items, tools=TOOLS, tool_choice=tool_choice)
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            break

        input_items += response.output                   # 모델의 도구 호출 항목을 그대로 되돌려 준다
        made_pending = False
        for call in calls:
            try:
                args = json.loads(call.arguments or "{}")
            except Exception:
                args = {}

            if call.name == "list_events":
                result = tool_list_events(args.get("start_date", ""), args.get("end_date", ""))
                statuses.append(["list_events", "done"])
            elif call.name in ("send_email", "add_calendar_event"):
                task = match_task_by_title(args.get("title")) if call.name == "add_calendar_event" else None
                if task and task.get("event_id"):
                    result = {"status": "skipped", "reason": "이미 캘린더에 등록된 업무입니다."}
                    statuses.append(["add_calendar_event", "skipped"])
                else:
                    queue_pending(call.name, args, task_id=task["id"] if task else None, msg_id=assistant_msg_id)
                    result = {"status": "pending_confirmation",
                              "message": "사용자 확인 대기 중입니다. 화면의 확인 창에서 버튼을 누르면 실행됩니다. 같은 도구를 다시 호출하지 마세요."}
                    statuses.append([call.name, "waiting"])
                    made_pending = True
            else:
                result = {"status": "failed", "error": f"알 수 없는 도구 {call.name}"}

            input_items.append({"type": "function_call_output", "call_id": call.call_id,
                                "output": json.dumps(result, ensure_ascii=False)})
        if made_pending:
            tool_choice = "none"                         # 확인 대기 중이면 더 호출하지 말고 답변만

    answer = (response.output_text or "").strip() if response else ""
    if not answer:
        answer = "내용을 준비했어요. 화면에 뜬 확인 창을 확인해 주세요." if st.session_state.pending_actions else "죄송해요, 답변을 만들지 못했어요. 다시 말씀해 주세요."
    return answer, statuses


# ---- (d) STT / TTS ----
def transcribe(audio_bytes):
    """음성 → 텍스트 (whisper-1)"""
    transcript = client.audio.transcriptions.create(
        model=STT_MODEL, file=("audio.wav", audio_bytes, "audio/wav"), language="ko")
    return transcript.text.strip()


def speak(text):
    """텍스트 → 음성(bytes). 최신 답변만 자동 재생"""
    st.session_state.tts_audio = None
    st.session_state.tts_autoplay = False
    if not client or not text:
        return
    speech_text = strip_for_speech(text)
    err = None
    with st.spinner("읽어 드릴게요…"):
        for model in (TTS_MODEL, "tts-1"):
            try:
                speech = client.audio.speech.create(model=model, voice=TTS_VOICE, input=speech_text)
                st.session_state.tts_audio = speech.content
                st.session_state.tts_autoplay = True
                return
            except Exception as e:
                err = e
    set_notice("note", f"음성 생성에 실패해 글로만 답했어요. ({err})")


# ---- (e) 사용자 메시지 1건 처리 ----
def handle_user_message(text, via, box):
    """사용자 발화 추가 → AIVLE 답변 → 음성 → rerun"""
    text = (text or "").strip()
    if not text:
        return
    st.session_state.tts_autoplay = False                 # 새 질문을 하면 읽던 음성은 멈춤
    user_msg = new_message("user", text, via=via)
    st.session_state.messages.append(user_msg)
    assistant_id = uuid.uuid4().hex[:8]

    with box:
        render_message(user_msg)
        if client is None:
            answer, statuses = "OPENAI_API_KEY 가 설정되지 않아 답변할 수 없어요. 사이드바 '설정 안내'를 확인해 주세요.", []
        else:
            with st.spinner(f"{APP_NAME}이 생각하는 중…"):
                try:
                    answer, statuses = run_able(assistant_id)
                except Exception as e:
                    answer, statuses = f"죄송해요, 답변 중 오류가 났어요. 잠시 후 다시 말씀해 주세요. ({e})", []
        msg = new_message("assistant", answer, tools=statuses, show_tasks=mentions_tasks(text, answer, st.session_state.tasks))
        msg["id"] = assistant_id
        st.session_state.messages.append(msg)
        st.session_state.messages = trim_history(st.session_state.messages)
    st.rerun()


# ---- (f) 확인 후 실행 ----
def do_calendar(action, title, date_iso, description):
    """캘린더 등록 1건. ('ok'|'skip'|'fail', 안내 문장). 실패하면 notice 를 남기고 대기열에 그대로 둔다"""
    title = (title or "").strip()
    if not title or not parse_iso(date_iso):
        set_notice("error", "일정 제목과 날짜를 확인해 주세요.")
        return "fail", None
    task = find_task(action.get("task_id")) or match_task_by_title(title)

    # 중복 방지 1: 이미 등록된 업무
    if task and task.get("event_id") and store_get(STORE, task["event_id"]):
        remove_pending(action["id"])
        update_tool_status(action, "skipped")
        return "skip", f"'{task['title']}' 일정은 이미 캘린더에 있어요."

    # 중복 방지 2: 같은 제목 + 같은 날짜 일정이 이미 있음
    existing = find_existing_event(title, date_iso, store_list(STORE, date_iso, date_iso))
    if existing:
        event_id = existing["id"]
        text = f"{fmt_long_kor(date_iso)}에 '{title}' 일정이 이미 있어서 그대로 두었어요."
    else:
        event_id = store_add(STORE, title=title, date=date_iso, description=description or "", source="able",
                             task_id=task["id"] if task else None)
        text = f"{fmt_long_kor(date_iso)}에 '{title}' 일정을 캘린더에 추가했어요."

    if task:
        task["due"] = date_iso
        task["event_id"] = event_id
    remove_pending(action["id"])
    update_tool_status(action, "done")
    return "ok", text


def execute_calendar(action, title, date_iso, description):
    status, text = do_calendar(action, title, date_iso, description)
    if status == "ok":
        append_assistant(text, tools=[["add_calendar_event", "done"]])
        st.toast("캘린더에 추가했어요.")
    elif status == "skip":
        set_notice("note", text)


def execute_calendar_all():
    """대기열의 캘린더 작업을 모두 실행 (제안 날짜 그대로)"""
    done_texts, skip_texts = [], []
    for a in list(st.session_state.pending_actions):
        if a["type"] != "calendar":
            continue
        args = a["args"]
        status, text = do_calendar(a, args.get("title"), args.get("date"), args.get("description"))
        if status == "ok":
            done_texts.append(text)
        elif status == "skip":
            skip_texts.append(text)
    if done_texts:
        append_assistant(" ".join(done_texts), tools=[["add_calendar_event", "done"]] * len(done_texts))
        st.toast(f"캘린더에 {len(done_texts)}건 추가했어요.")
    elif skip_texts:
        set_notice("note", " ".join(skip_texts))


def execute_email(action, to_label, to_email, subject, body):
    """확인된 메일 발송: 확인 창에 입력한 주소로 보낸다"""
    if not is_email(to_email):
        set_notice("error", "받는 사람 이메일 주소를 확인해 주세요. (예: name@gmail.com)")
        return
    if not GMAIL_OK:
        set_notice("note", "Gmail 이 설정되지 않아 메일을 보낼 수 없어요. 사이드바 '설정 안내'를 열어 GMAIL_ADDRESS, GMAIL_APP_PASSWORD 를 추가한 뒤 다시 '보내기'를 눌러 주세요.")
        return
    with st.spinner("메일을 보내는 중…"):
        result = send_email(to_email.strip(), subject.strip(), body)       # 입력한 주소로 실제 발송
    if result.get("status") == "success":
        remove_pending(action["id"])
        update_tool_status(action, "done")
        st.session_state.emails_sent += 1
        append_assistant(f"{to_label}에게 메일을 보냈어요. 제목은 '{subject.strip()}' 입니다.",
                         tools=[["send_email", "done"]])
        st.toast(f"메일을 보냈어요 → {to_email.strip()}")
    else:
        set_notice("error", f"메일 발송에 실패했어요: {result.get('error')} — Secrets 의 GMAIL_ADDRESS / GMAIL_APP_PASSWORD(앱 비밀번호 16자리)를 확인하고 다시 '보내기'를 눌러 주세요.")


def cancel_action(action):
    remove_pending(action["id"])
    update_tool_status(action, "cancelled")
    st.session_state.tts_autoplay = False


def dismiss_current_action():
    """확인 창을 X 나 바깥 클릭으로 닫으면 '취소'와 같게 처리"""
    a = current_action()
    if a:
        cancel_action(a)


# ---- (g) 협업·미팅 요청 보내기 / 응답 ----
def open_request(task=None, event=None):
    """요청 다이얼로그 기본값 채우기"""
    subject = task["title"] if task else (event or {}).get("title", "일정")
    if task and task.get("due"):
        d = parse_iso(task["due"])
    elif event and event.get("date"):
        d = parse_iso(event["date"])
    else:
        d = today + timedelta(days=1)
    st.session_state.request_form = {
        "task_id": task["id"] if task else None, "event_id": (event or {}).get("id"), "subject": subject,
        "to": [TEAMMATES[0]], "type": REQUEST_TYPES[0], "date": (d if d and d >= today else today + timedelta(days=1)).isoformat(),
        "start": "10:00", "duration": 60,
        "message": request_message(task, event, (st.session_state.briefing or {}).get("title")),
    }
    st.session_state.request_mode = "summary"


def send_request(form):
    """요청을 공용 캘린더에 '대기' 일정으로 저장 + 받는 사람에게 메일 (앱 링크 포함)"""
    end = end_time_of(form["start"], form["duration"])
    eid = store_add(STORE, title=request_title(form["type"], form["subject"], "pending"), date=form["date"],
                    start_time=form["start"], end_time=end, description=form["message"], source="request", kind="request",
                    status="pending", request_type=form["type"], subject=form["subject"], **{"from": USER_NAME},
                    to=list(form["to"]), task_id=form.get("task_id"), message=form["message"])
    sent, failed = 0, []
    for name in form["to"]:
        link = request_link(eid, name)
        body = (f"{form['message']}\n\n[일시] {fmt_kor_day(form['date'])} {form['start']}~{end} ({form['duration']}분)\n"
                + (f"[수락/거절하기] {link}\n" if link else "") + f"\n— {APP_NAME} (김 대리의 AI 비서)")
        if GMAIL_OK:
            result = send_demo_email(name, CONTACT_EMAIL.get(name, ""), f"[{form['type']}] {form['subject']} — {USER_NAME}", body)
            if result.get("status") == "success":
                sent += 1
            else:
                failed.append(f"{name}: {result.get('error')}")
    st.session_state.req_status_seen[eid] = "pending"
    names = ", ".join(form["to"])
    text = (f"{names}에게 '{form['subject']}' {form['type']}을 보냈어요. {fmt_kor_day(form['date'])} {form['start']}부터 {form['duration']}분이에요. "
            + ("답장이 오면 캘린더 상태가 바뀌어요." if sent else "메일은 보내지 못했지만 요청은 캘린더에 대기 상태로 올렸어요."))
    append_assistant(text, tools=[["request", "sent"]] * max(1, len(form["to"])))
    if failed:
        set_notice("error", "일부 메일 발송 실패: " + "; ".join(failed) + " — Gmail 설정을 확인해 주세요.")
    elif not GMAIL_OK:
        set_notice("note", "Gmail 이 설정되지 않아 메일은 보내지 않았어요. 요청은 캘린더에 올라갔고, 사이드바 '보기 모드'로 팀원 화면을 확인할 수 있어요.")
    st.toast(f"{form['type']}을 보냈어요" + (f" (메일 {sent}통 → {MY_EMAIL})" if sent else ""))
    return eid


def decide_request(ev, decision, by, reason=""):
    """팀원이 수락/거절 → 일정 상태 갱신 + 김 대리에게 알림 메일"""
    updates = apply_decision(ev, decision, by, reason)          # 거절 이유 없으면 ValueError
    store_update(STORE, ev["id"], **updates)
    verb = "수락" if decision == "accepted" else "거절"
    body = (f"{by}님이 '{ev.get('subject')}' {ev.get('request_type')}을 {verb}했어요.\n"
            f"[일시] {fmt_when(ev)}\n" + (f"[거절 이유] {updates['reason']}\n" if decision == "rejected" else "")
            + f"\n— {APP_NAME}")
    if GMAIL_OK:
        send_demo_email(USER_NAME, MY_EMAIL, f"[{verb}] {ev.get('subject')} — {by}", body)
    st.toast(f"{verb}했어요. {USER_NAME}에게 알림을 보냈어요." if GMAIL_OK else f"{verb}했어요.")


# =========================================================
# 6) 다이얼로그 (한 실행에 하나만 연다)
#    - 대기열/상태가 있으면 매 실행마다 열어 준다. 결정 후 st.rerun() 으로 닫는다.
# =========================================================
def right_row(n):
    """버튼 n개를 오른쪽 끝에 모으는 칸. 반환 순서: 첫 번째(주 버튼)가 가장 오른쪽"""
    cols = st.columns([5 - n] + [1.2] * n, gap="small", vertical_alignment="center")
    return list(reversed(cols[1:]))


def dlg_row(key, value):
    st.markdown(f'<div class="aivle-dlg-row"><span class="aivle-dlg-k">{esc(key)}</span><span class="aivle-dlg-v">{esc(value)}</span></div>',
                unsafe_allow_html=True)


def dlg_prepare(action):
    """작업이 바뀌면 읽기 모드로 되돌린다. (대기 건수, 모두 캘린더인지) 반환"""
    if st.session_state.dlg_action_id != action["id"]:
        st.session_state.dlg_action_id = action["id"]
        st.session_state.dlg_mode = "summary"
    total = len(st.session_state.pending_actions)
    all_calendar = all(a["type"] == "calendar" for a in st.session_state.pending_actions)
    if total > 1:
        st.markdown(f'<span class="aivle-dlg-count">확인할 작업 1 / {total}</span>', unsafe_allow_html=True)
    render_notice()
    return total, all_calendar


@st.dialog("캘린더에 추가할까요?", width="medium", on_dismiss=dismiss_current_action)
def calendar_dialog():
    action = current_action()
    if not action or action["type"] != "calendar":
        return
    aid, args = action["id"], action["args"]
    total, all_calendar = dlg_prepare(action)
    task = find_task(action.get("task_id"))
    undated = bool(task) and not task.get("due")          # 마감 미정 업무: AIVLE 제안 / 직접 지정
    skip_label = "건너뛰기" if total > 1 else "취소"

    if st.session_state.dlg_mode == "summary":
        dlg_row("일정 제목", args.get("title", ""))
        date_iso = args.get("date")
        if undated:
            sd = task.get("suggested_due") or date_iso
            options = [f"{APP_NAME} 제안: {fmt_kor(sd)} — {task.get('suggest_reason') or '회의 후 1주'}", "직접 지정"]
            choice = st.radio("날짜", options, key=f"dlg_radio_{aid}")
            date_iso = sd
            if choice == "직접 지정":
                date_iso = st.date_input("직접 지정", value=parse_iso(sd) or today, key=f"dlg_date_{aid}", format="YYYY-MM-DD").isoformat()
        else:
            dlg_row("날짜", fmt_long_kor(date_iso))
        dlg_row("메모", args.get("description", ""))

        b1, b2, b3 = right_row(3)
        if b1.button("추가", key=f"dlg_add_{aid}", type="primary"):
            execute_calendar(action, args.get("title"), date_iso, args.get("description"))
            st.rerun()
        if b2.button("수정하기", key=f"dlg_edit_{aid}"):
            st.session_state.dlg_mode = "edit"
            st.rerun()
        if b3.button(skip_label, key=f"dlg_cancel_{aid}"):
            cancel_action(action)
            st.rerun()
        if total > 1 and all_calendar:
            if st.button(f"남은 {total}건 모두 그대로 추가", key=f"dlg_addall_{aid}"):
                execute_calendar_all()
                st.rerun()
    else:
        title = st.text_input("일정 제목", value=args.get("title", ""), key=f"dlg_etitle_{aid}")
        d = st.date_input("날짜", value=parse_iso(args.get("date")) or today, key=f"dlg_edate_{aid}", format="YYYY-MM-DD")
        desc = st.text_area("메모", value=args.get("description", ""), height=120, key=f"dlg_edesc_{aid}")
        b1, b2 = right_row(2)
        if b1.button("저장하고 추가", key=f"dlg_save_{aid}", type="primary"):
            st.session_state.dlg_mode = "summary"
            execute_calendar(action, title, d.isoformat(), desc)
            st.rerun()
        if b2.button("돌아가기", key=f"dlg_back_{aid}"):
            st.session_state.dlg_mode = "summary"
            st.rerun()


@st.dialog("메일을 보낼까요?", width="medium", on_dismiss=dismiss_current_action)
def email_dialog():
    action = current_action()
    if not action or action["type"] != "email":
        return
    aid, args = action["id"], action["args"]
    total, _ = dlg_prepare(action)
    skip_label = "건너뛰기" if total > 1 else "취소"

    # 받는 사람 이름 · 메일 주소 (위아래 입력칸). 주소록의 가상 주소는 비워 두고 직접 입력받는다
    if f"dlg_ename_{aid}" not in st.session_state:
        addr = args.get("to_email") or ""
        st.session_state[f"dlg_ename_{aid}"] = args.get("to_label") or ""
        st.session_state[f"dlg_eaddr_{aid}"] = "" if addr.endswith("@aivle-demo.kr") else addr
    to_label = st.text_input("받는 사람", key=f"dlg_ename_{aid}", placeholder="예: 팀장님")
    to_email = st.text_input("메일 주소", key=f"dlg_eaddr_{aid}", placeholder="예: name@gmail.com")
    args["to_label"], args["to_email"] = to_label, to_email

    if st.session_state.dlg_mode == "summary":
        dlg_row("제목", args.get("subject", ""))
        dlg_row("본문", args.get("body", ""))
        b1, b2, b3 = right_row(3)
        if b1.button("보내기", key=f"dlg_send_{aid}", type="primary"):
            execute_email(action, to_label or to_email, to_email, args.get("subject", ""), args.get("body", ""))
            st.rerun()
        if b2.button("수정하기", key=f"dlg_edit_{aid}"):
            st.session_state.dlg_mode = "edit"
            st.rerun()
        if b3.button(skip_label, key=f"dlg_cancel_{aid}"):
            cancel_action(action)
            st.rerun()
    else:
        subject = st.text_input("제목", value=args.get("subject", ""), key=f"dlg_esubject_{aid}")
        body = st.text_area("본문", value=args.get("body", ""), height=220, key=f"dlg_ebody_{aid}")
        b1, b2 = right_row(2)
        if b1.button("저장하고 보내기", key=f"dlg_save_{aid}", type="primary"):
            st.session_state.dlg_mode = "summary"
            args.update(subject=subject, body=body)
            execute_email(action, to_label or to_email, to_email, subject, body)
            st.rerun()
        if b2.button("돌아가기", key=f"dlg_back_{aid}"):
            args.update(subject=subject, body=body)
            st.session_state.dlg_mode = "summary"
            st.rerun()


def close_event():
    st.session_state.open_event = None


@st.dialog("일정", width="medium", on_dismiss=close_event)
def event_dialog():
    ev = store_get(STORE, st.session_state.open_event)
    if not ev:
        st.markdown('<p class="aivle-hint">일정을 찾을 수 없어요.</p>', unsafe_allow_html=True)
        return
    render_notice()
    is_owner = st.session_state.view_as == USER_NAME
    is_request = ev.get("kind") == "request"
    task = find_task(ev.get("task_id")) if ev.get("task_id") else None

    dlg_row("제목", ev["title"])
    dlg_row("일시", fmt_when(ev))
    kind_label = "협업·미팅 요청" if is_request else (f"{APP_NAME}이 추가한 업무" if ev.get("source") == "able" else "캘린더 일정")
    dlg_row("구분", kind_label)
    if is_request:
        status_kr = {"pending": "대기 (답장 전)", "accepted": f"확정 — {ev.get('decided_by') or ''}", "rejected": f"거절됨 — {ev.get('decided_by') or ''}"}.get(ev.get("status"), ev.get("status"))
        dlg_row("상태", status_kr)
        dlg_row("보낸 사람", ev.get("from") or "")
        dlg_row("받는 사람", ", ".join(ev.get("to") or []))
        if ev.get("reason"):
            dlg_row("거절 이유", ev["reason"])
        dlg_row("메시지", ev.get("message") or "")
    else:
        if ev.get("status") == "done":
            dlg_row("상태", "✓ 완료")
        dlg_row("메모", ev.get("description") or "")

    # 버튼은 오른쪽 끝, 주 버튼이 가장 오른쪽 (닫기는 오른쪽 위 X)
    if is_owner and not is_request:
        btns = [("ev_req", "협업·미팅 요청", "primary")]
        if task and ev.get("source") == "able":
            if ev.get("status") != "done":
                btns.append(("ev_done", "완료 표시", "secondary"))
            btns.append(("ev_draft", "초안 맡기기", "secondary"))
        clicked = None
        for slot, (key, label, kind) in zip(right_row(len(btns)), btns):
            if slot.button(label, key=key, type=kind):
                clicked = key
        if clicked == "ev_req":
            open_request(task=task, event=ev)
            close_event()
            st.rerun()
        elif clicked == "ev_done":
            mark_task_done(task, True)
            close_event()
            st.toast("완료로 표시했어요.")
            st.rerun()
        elif clicked == "ev_draft":
            st.session_state.draft_task = task["id"]
            close_event()
            st.rerun()
    elif not is_owner:
        me = st.session_state.view_as
        if is_request and me in (ev.get("to") or []) and ev.get("status") == "pending":
            slot = st.container(horizontal=True, horizontal_alignment="right")
            if slot.button("수락/거절하러 가기", key="ev_go_requests", type="primary"):
                close_event()
                go("requests", focus_request=ev["id"])


def close_request():
    st.session_state.request_form = None


@st.dialog("협업·미팅 요청", width="medium", on_dismiss=close_request)
def request_dialog():
    form = st.session_state.request_form
    if not form:
        return
    render_notice()
    if st.session_state.request_mode == "summary":
        dlg_row("받는 사람", ", ".join(form["to"]) or "(선택 필요)")
        dlg_row("종류", form["type"])
        dlg_row("일시", f"{fmt_kor_day(form['date'])} {form['start']}~{end_time_of(form['start'], form['duration'])} ({form['duration']}분)")
        dlg_row("관련 업무", form["subject"])
        dlg_row("메시지", form["message"])
        b1, b2, b3 = right_row(3)
        if b1.button("보내기", key="rq_send", type="primary", disabled=not form["to"]):
            send_request(form)
            close_request()
            st.rerun()
        if b2.button("수정하기", key="rq_edit"):
            st.session_state.request_mode = "edit"
            st.rerun()
        if b3.button("취소", key="rq_cancel"):
            close_request()
            st.rerun()
    else:
        to = st.multiselect("받는 사람", TEAMMATES, default=form["to"], key="rq_to")
        rtype = st.radio("종류", REQUEST_TYPES, index=REQUEST_TYPES.index(form["type"]), horizontal=True, key="rq_type")
        c1, c2, c3 = st.columns(3)
        d = c1.date_input("날짜", value=parse_iso(form["date"]) or today, key="rq_date", format="YYYY-MM-DD")
        h, m = [int(x) for x in form["start"].split(":")]
        t = c2.time_input("시작 시간", value=time(h, m), step=timedelta(minutes=30), key="rq_start")
        dur = c3.selectbox("소요 시간", DURATIONS, index=DURATIONS.index(form["duration"]), format_func=lambda x: f"{x}분", key="rq_dur")
        msg = st.text_area("메시지", value=form["message"], height=180, key="rq_msg")
        b1, b2 = right_row(2)
        if b1.button("저장", key="rq_save", type="primary"):
            form.update(to=to, type=rtype, date=d.isoformat(), start=t.strftime("%H:%M"), duration=dur, message=msg)
            st.session_state.request_mode = "summary"
            st.rerun()
        if b2.button("돌아가기", key="rq_back"):
            st.session_state.request_mode = "summary"
            st.rerun()


def close_draft():
    st.session_state.draft_task = None


@st.dialog(f"{APP_NAME} 초안", width="large", on_dismiss=close_draft)
def draft_dialog():
    task = find_task(st.session_state.draft_task)
    if not task:
        return
    tid = task["id"]
    render_notice()
    st.markdown(f'<p class="aivle-eyebrow">{esc(task["title"])} · {esc(task_due_label(task))}</p>', unsafe_allow_html=True)
    if tid not in st.session_state.drafts:
        if client is None:
            st.session_state.drafts[tid] = "(OPENAI_API_KEY 가 없어 초안을 쓸 수 없어요. 이 칸에 직접 작성해도 됩니다.)"
        else:
            try:
                with st.spinner(f"{APP_NAME}이 초안을 쓰는 중…"):
                    st.session_state.drafts[tid] = generate_draft(task)
                st.toast("초안을 썼어요. 수정해서 쓰세요.")
            except Exception as e:
                st.session_state.drafts[tid] = ""
                set_notice("error", f"초안 작성에 실패했어요: {e} — '다시 쓰기'를 눌러 주세요.")
    rev = st.session_state.draft_rev.get(tid, 0)
    text = st.text_area("초안 (수정 가능)", value=st.session_state.drafts.get(tid, ""), height=320, key=f"draft_ta_{tid}_{rev}")
    st.session_state.drafts[tid] = text
    _, b1, b2 = st.columns([4, 1, 1], vertical_alignment="center")       # 버튼은 오른쪽 끝
    if b1.button("다시 쓰기", key=f"draft_again_{tid}", disabled=client is None):
        st.session_state.drafts.pop(tid, None)
        st.session_state.draft_rev[tid] = rev + 1
        st.rerun()
    with b2:                                                              # 클립보드 복사 (작은 HTML 버튼)
        components.html(
            "<button id='c' style=\"width:100%;height:44px;border-radius:12px;border:none;background:#5B4BE0;color:#fff;"
            "font:500 14px 'Noto Sans KR',sans-serif;cursor:pointer\">복사</button>"
            f"<script>const t={json.dumps(text)};document.getElementById('c').onclick=function(){{"
            "const a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();"
            "try{document.execCommand('copy');}catch(e){}a.remove();"
            "if(navigator.clipboard){navigator.clipboard.writeText(t).catch(()=>{});}"
            "this.textContent='복사됨';setTimeout(()=>this.textContent='복사',1500);};</script>",
            height=48)


def render_dialogs():
    """우선순위: 확인 대기(캘린더/메일) → 요청 작성 → 초안 → 일정 보기"""
    action_now = current_action()
    if action_now:
        calendar_dialog() if action_now["type"] == "calendar" else email_dialog()
    elif st.session_state.request_form:
        request_dialog()
    elif st.session_state.draft_task:
        draft_dialog()
    elif st.session_state.open_event:
        event_dialog()


# =========================================================
# 7) 화면
# =========================================================
def build_context():
    has_meeting = st.session_state.meeting_text is not None
    registered_any = any(t.get("event_id") for t in st.session_state.tasks)
    emailed_any = st.session_state.emails_sent > 0
    step_now, steps_done = compute_steps(has_meeting, registered_any, emailed_any)
    cal_y, cal_m = st.session_state.cal_year, st.session_state.cal_month
    m_start, m_end = month_range(cal_y, cal_m)
    all_events = store_list(STORE)
    return {
        "has_meeting": has_meeting, "step_now": step_now, "steps_done": steps_done,
        "cal_y": cal_y, "cal_m": cal_m,
        "month_events": [e for e in all_events if m_start <= e["date"] <= m_end],
        "all_events": all_events,
        "is_owner": st.session_state.view_as == USER_NAME,
    }


def render_message(m):
    """대화 말풍선 (HTML). 나 · 음성 / 나 · 입력 / AIVLE"""
    if m["role"] == "user":
        label = "나 · 음성" if m.get("via") == "voice" else "나 · 입력"
        st.markdown(f'<div class="aivle-msg-u"><span class="aivle-msg-label">{label}</span>'
                    f'<div class="aivle-bubble-u">{esc(m["content"])}</div></div>', unsafe_allow_html=True)
    else:
        tools_html = "".join(f'<span class="aivle-tool">— {esc(line)}</span>' for line in tool_lines(m.get("tools")))
        with st.container(horizontal=True, vertical_alignment="center", gap="small", key=f"ahead_{m['id']}"):
            st.markdown(f'<span class="aivle-msg-label">{APP_NAME}</span>', unsafe_allow_html=True)
            playing = st.session_state.get("tts_for") == m["id"] and st.session_state.tts_autoplay
            if st.button("", key=f"spk_{m['id']}", icon=":material/stop_circle:" if playing else ":material/volume_up:",
                         type="tertiary", help="읽기 멈추기" if playing else "음성으로 듣기"):
                if playing:                                   # 다시 누르면 멈춤 (오디오 요소를 지움)
                    st.session_state.tts_autoplay = False
                else:
                    st.session_state.tts_for = m["id"]
                    speak(m["content"])
                st.rerun()
        st.markdown(f'<div class="aivle-msg-a" style="margin-top:0"><div class="aivle-bubble-a">{esc(m["content"])}{tools_html}</div></div>',
                    unsafe_allow_html=True)


def render_task_links(msg_id):
    """답변 아래 업무 카드 (버튼 행). 누르면 '내 업무' 페이지에서 그 업무를 펼쳐 보여준다"""
    for i, t in enumerate(st.session_state.tasks):
        state = {"done": " · ✓ 완료", "scheduled": " · ✓ 캘린더에 추가됨"}.get(task_status(t), "")
        label = f"{i + 1}  {t['title']}  ·  {task_due_label(t)}{state}   —  내 업무에서 보기 →"
        if st.button(label, key=f"tlink_{msg_id}_{t['id']}"):
            go("tasks", selected_task=t["id"])


def render_sidebar(ctx):
    """사이드바: 브랜드, 보기 모드, 메뉴, 단계, 연결 상태, 설정 안내, 데모 초기화"""
    with st.sidebar:
        st.markdown(f'<div class="aivle-brand"><i>A</i><span class="aivle-wordmark">{APP_NAME}</span></div>', unsafe_allow_html=True)

        # 보기 모드 (시연: 팀원 화면으로 전환)
        names = [USER_NAME] + TEAMMATES
        picked = st.selectbox("보기 모드", names, index=names.index(st.session_state.view_as), key="view_mode_select",
                              help="팀원을 고르면 그 사람이 받은 요청을 처리하는 화면이 돼요.")
        if picked != st.session_state.view_as:
            st.session_state.view_as = picked
            st.session_state.page = "assistant" if picked == USER_NAME else "requests"
            st.rerun()
        is_owner = picked == USER_NAME
        page = st.session_state.page

        if is_owner:
            n_tasks = len(st.session_state.tasks)
            if st.button(PAGES["assistant"], key="nav_assistant", icon=":material/forum:", type="primary" if page == "assistant" else "secondary"):
                go("assistant")
            if st.button(PAGES["summary"], key="nav_summary", icon=":material/summarize:", type="primary" if page == "summary" else "secondary"):
                go("summary")
            if st.button(PAGES["tasks"] + (f"  ({n_tasks})" if n_tasks else ""), key="nav_tasks", icon=":material/task_alt:", type="primary" if page == "tasks" else "secondary"):
                go("tasks")
            if st.button(PAGES["calendar"], key="nav_calendar", icon=":material/calendar_month:", type="primary" if page == "calendar" else "secondary"):
                go("calendar")
        else:
            n_req = sum(1 for e in ctx["all_events"] if e.get("kind") == "request" and e.get("status") == "pending" and picked in (e.get("to") or []))
            if st.button(f"{PAGES['requests']}  ({n_req})", key="nav_requests", icon=":material/inbox:", type="primary" if page == "requests" else "secondary"):
                go("requests")
            if st.button(PAGES["calendar"], key="nav_calendar", icon=":material/calendar_month:", type="primary" if page == "calendar" else "secondary"):
                go("calendar")

        # 데이터 초기화 (확인 후 실행)
        st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
        if not st.session_state.confirm_reset:
            if st.button("데이터 초기화", key="btn_reset"):
                st.session_state.confirm_reset = True
                st.rerun()
        else:
            st.markdown('<p class="aivle-hint">일정·요청이 모두 지워져요.</p>', unsafe_allow_html=True)
            r1, r2 = st.columns(2)
            if r1.button("초기화", key="btn_reset_yes"):
                store_reset(STORE, today.isoformat())
                for t in st.session_state.tasks:
                    t["event_id"], t["done"] = None, False
                st.session_state.pending_actions = []
                st.session_state.req_status_seen = {}
                st.session_state.confirm_reset = False
                st.toast("데이터를 초기화했어요.")
                st.rerun()
            if r2.button("취소", key="btn_reset_no"):
                st.session_state.confirm_reset = False
                st.rerun()

        # 연결 상태 (맨 아래)
        def dot(ok):
            return f'<i style="background:{"#10B981" if ok else "#C4C4D4"}"></i>'
        st.markdown('<div style="height:16px"></div><div class="aivle-conn">'
                    f'<span>{dot(bool(client))}OpenAI {"연결됨" if client else "설정 필요"}</span>'
                    f'<span>{dot(GMAIL_OK)}Gmail {"연결됨" if GMAIL_OK else "설정 필요"}</span></div>', unsafe_allow_html=True)

        missing = missing_secrets(OPENAI_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        if missing:
            with st.expander("설정 안내", expanded=False):
                st.markdown("빠진 Secrets 키: " + ", ".join(f"`{k}`" for k in missing))
                st.markdown(
                    "- Streamlit Community Cloud → 앱 ⋮ → **Settings → Secrets** 에 키를 추가하면 앱이 자동으로 다시 시작돼요.\n"
                    "- `OPENAI_API_KEY` 가 없으면 대화·분석·음성이, `GMAIL_*` 이 없으면 메일 발송이 동작하지 않아요.\n"
                    f"- `MY_EMAIL`(선택): 모든 데모 메일이 도착할 주소. 없으면 `{DEFAULT_MY_EMAIL}` 을 써요.\n"
                    "- `APP_URL`(선택): 요청 메일에 넣을 이 앱의 주소. 자세한 순서는 **Secrets 설정 가이드.md** 를 보세요."
                )


def render_meeting_strip(ctx):
    """회의록 카드: 불러온 회의록 요약 + [다른 회의록 올리기]. 없으면(또는 다시 열면) 업로드 블록"""
    has_meeting = ctx["has_meeting"]
    show_upload = (not has_meeting) or st.session_state.show_uploader

    if has_meeting and not show_upload:
        b = st.session_state.briefing
        title = f" · {b['title']}" if b else ""
        with st.container(key="card_meeting"):
            with st.container(horizontal=True, vertical_alignment="center", key="meeting_row"):
                st.markdown('<p class="aivle-eyebrow">지금 읽고 있는 회의록</p>'
                            f'<p class="aivle-strong">{esc(st.session_state.meeting_name)}{esc(title)} · {fmt_kor_day(st.session_state.meeting_date)}</p>',
                            unsafe_allow_html=True)
                st.space("stretch")
                if st.button("다른 회의록 올리기", key="btn_other_meeting", icon=":material/upload_file:"):
                    st.session_state.show_uploader = True
                    st.rerun()
        return

    with st.container(key="card_upload"):
        u1, u2 = st.columns([2.4, 1], vertical_alignment="top", gap="medium")
        uploaded = u1.file_uploader("회의록 파일(.txt) 올리기", type=["txt"], key="uploader")
        meeting_date_input = u2.date_input("회의 날짜", value=parse_iso(st.session_state.meeting_date) or today, format="YYYY-MM-DD")
        if has_meeting and st.button("닫기", key="btn_close_uploader"):
            st.session_state.show_uploader = False
            st.rerun()
        if uploaded is not None:
            raw = uploaded.getvalue()
            key = (uploaded.name, hashlib.md5(raw).hexdigest(), meeting_date_input.isoformat())
            if key != st.session_state.briefing_key:          # 새 파일 또는 새 날짜일 때만 분석
                load_meeting(decode_text(raw), uploaded.name, meeting_date_input, key)
                st.rerun()
            elif st.session_state.show_uploader:
                st.session_state.show_uploader = False
                st.toast("이미 불러온 회의록이에요.")
                st.rerun()
        if has_meeting and not st.session_state.briefing:
            st.markdown('<p class="aivle-hint">회의록은 기억하고 있지만 분석 결과가 없어요.</p>', unsafe_allow_html=True)
            if st.button("다시 분석", key="btn_reanalyze"):
                load_meeting(st.session_state.meeting_text, st.session_state.meeting_name, parse_iso(st.session_state.meeting_date) or today,
                             st.session_state.briefing_key or ("retry",))
                st.rerun()


def render_assistant(ctx):
    """페이지: AIVLE에게 부탁하기 — 회의록 카드 → 대화 카드(기록 → 예시 명령 → 작성기)"""
    has_meeting = ctx["has_meeting"]
    render_meeting_strip(ctx)
    incoming, incoming_via = None, "text"
    if st.session_state.prefill:                                  # 다른 페이지에서 넘어온 문장
        incoming, st.session_state.prefill = st.session_state.prefill, None

    with st.container(key="card_chat"):
        # (0) 머리줄: 제목 · 대화 기억 배지 · 대화 비우기 (오른쪽 끝)
        with st.container(horizontal=True, vertical_alignment="center", key="chat_head"):
            st.markdown(f'<span class="aivle-card-title" style="margin:0">{APP_NAME}와 대화</span>', unsafe_allow_html=True)
            st.space("stretch")
            st.markdown(f'<span class="aivle-pill">대화 기억 {count_turns(st.session_state.messages)} / {MAX_TURNS}턴</span>', unsafe_allow_html=True)
            if st.button("대화 비우기", key="btn_clear", icon=":material/delete_sweep:", type="tertiary"):
                st.session_state.messages = []
                st.session_state.pending_actions = []
                st.session_state.tts_audio = None
                st.session_state.tts_autoplay = False
                st.toast("대화를 비웠어요.")
                st.rerun()

        # (1) 대화 기록 — 오래된 것부터, 최신이 아래 (자동 스크롤)
        history_box = st.container(height=400, border=False, autoscroll=True)
        with history_box:
            msgs = st.session_state.messages
            if True:                                                # 첫 인사는 대화가 쌓여도 맨 위에 항상 보임
                st.markdown(f'<div class="aivle-msg-a"><span class="aivle-msg-label">{APP_NAME}</span><div class="aivle-bubble-a">'
                            f'안녕하세요, {APP_NAME}이에요. 위에서 회의록을 올리면 요약하고 {USER_NAME}님 업무를 정리해 드릴게요. '
                            '아래 마이크나 입력창으로 명령해 주세요.</div></div>', unsafe_allow_html=True)
            for m in msgs:
                render_message(m)
                # 스피커로 요청한 답변만, 플레이어 없이 재생 (멈추면 요소를 지워 소리 정지)
                if st.session_state.get("tts_for") == m["id"] and st.session_state.tts_audio and st.session_state.tts_autoplay:
                    b64 = base64.b64encode(st.session_state.tts_audio).decode("ascii")
                    st.markdown(f'<audio autoplay src="data:audio/mp3;base64,{b64}" style="display:none"></audio>', unsafe_allow_html=True)

        # (2) 예시 명령 (회의록이 필요한 것은 없으면 비활성)
        q1, q2, q3, q4 = st.columns(4)
        if q1.button("회의 요약 들려줘", key="chip_summary", disabled=not has_meeting):
            incoming = "오늘 회의 내용을 요약해서 들려줘"
        if q2.button("내 업무 메일로 보내줘", key="chip_mail", disabled=not has_meeting):
            incoming = "회의 요약과 내 업무를 정리해서 내 메일로 보내줘"
        if q3.button("업무 전부 캘린더에 넣어줘", key="chip_calendar", disabled=not has_meeting):
            incoming = "내 업무를 전부 캘린더에 등록해줘"
        if q4.button("이번 주 일정 알려줘", key="chip_week"):
            incoming = "이번 주 일정 알려줘"

        # (3) 작성기: 마이크 + 텍스트 + 전송 (한 줄)
        cm, cf = st.columns([0.5, 9], vertical_alignment="center", gap="small")
        with cm:
            with st.container(key="mic_box"):
                audio_value = st.audio_input("눌러서 말하기", key=f"mic_{st.session_state.mic_n}", label_visibility="collapsed")
        with cf:
            with st.form("msg_form", clear_on_submit=True, border=False):
                f1, f2 = st.columns([8, 1], vertical_alignment="center", gap="small")
                typed = f1.text_input("명령 입력", placeholder=f"{APP_NAME}에게 명령하기 (예: 팀장님께 업무 정리 메일 보내줘)", label_visibility="collapsed")
                sent = f2.form_submit_button("전송", width="stretch")
        if sent and typed.strip():
            incoming, incoming_via = typed, "text"

        pending_slot = st.empty()                                   # 처리 중 스피너 자리
        if audio_value is not None:                                 # 같은 녹음은 한 번만
            audio_bytes = audio_value.getvalue()
            audio_hash = hashlib.md5(audio_bytes).hexdigest()
            if audio_hash != st.session_state.last_audio_hash:
                st.session_state.last_audio_hash = audio_hash
                st.session_state.mic_n += 1                     # 다음 실행에서 마이크를 새로 (재생 버튼 대신 마이크)
                if client is None:
                    set_notice("note", "OPENAI_API_KEY 가 없어 음성을 인식할 수 없어요. (사이드바 '설정 안내' 참고)")
                else:
                    try:
                        with pending_slot.container(), st.spinner("음성을 글로 바꾸는 중…"):
                            heard = transcribe(audio_bytes)
                        if heard:
                            st.toast(f"이렇게 들었어요: {heard[:40]}")
                            incoming, incoming_via = heard, "voice"
                        else:
                            set_notice("warning", "음성을 알아듣지 못했어요. 조금 더 길게 말하고 다시 녹음해 주세요.")
                    except Exception as e:
                        set_notice("error", f"음성 인식에 실패했어요: {e} — 다시 녹음해 주세요.")

        if incoming:                                                # 버튼 / 텍스트 / 음성 / 다른 페이지에서 넘어온 문장
            handle_user_message(incoming, incoming_via, history_box)


def render_summary(ctx):
    """페이지: 회의록 요약 — 회의록 카드 → 요약 카드(수정 가능) → [다시 요약] [txt로 저장] [메일로 보내기]"""
    render_meeting_strip(ctx)
    if not ctx["has_meeting"]:
        return
    key = st.session_state.briefing_key
    with st.container(key="card_summary"):
        with st.container(horizontal=True, vertical_alignment="center", key="sum_head"):
            st.markdown('<span class="aivle-card-title" style="margin:0">회의록 요약</span>', unsafe_allow_html=True)
            st.space("stretch")
            st.markdown(f'<span class="aivle-pill">{esc(st.session_state.meeting_name)} · {fmt_kor_day(st.session_state.meeting_date)}</span>',
                        unsafe_allow_html=True)

        if st.session_state.summary_key != key or st.session_state.summary_text is None:
            if client is None:
                st.session_state.summary_text = ""
                set_notice("note", "OPENAI_API_KEY 가 없어 요약을 만들 수 없어요. (사이드바 '설정 안내' 참고)")
            else:
                try:
                    with st.spinner("회의록을 정리하는 중…"):
                        st.session_state.summary_text = generate_summary(st.session_state.meeting_text, st.session_state.meeting_date)
                    st.toast("회의록 요약을 만들었어요.")
                except Exception as e:
                    st.session_state.summary_text = ""
                    set_notice("error", f"요약에 실패했어요: {e} — '다시 요약'을 눌러 주세요.")
            st.session_state.summary_key = key
            st.session_state.summary_rev += 1                    # 새 요약을 칸에 반영 (키가 같으면 예전 값 유지됨)
            render_notice()

        text = st.text_area("요약 (수정 가능)", value=st.session_state.summary_text or "", height=520,
                            key=f"sum_ta_{st.session_state.summary_rev}", label_visibility="collapsed")
        st.session_state.summary_text = text

        stem = os.path.splitext(st.session_state.meeting_name or "meeting")[0]
        fname = f"{st.session_state.meeting_date}_{stem}_요약.txt"
        with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", gap="small", key="sum_actions"):
            if st.button("다시 요약", key="btn_sum_again", icon=":material/refresh:", disabled=client is None):
                st.session_state.summary_text = None
                st.session_state.summary_rev += 1
                st.rerun()
            st.download_button("txt로 저장", data=(text or "").encode("utf-8"), file_name=fname, mime="text/plain",
                               key="btn_sum_txt", icon=":material/download:", disabled=not text.strip())
            if st.button("메일로 보내기", key="btn_sum_mail", icon=":material/send:", type="primary", disabled=not text.strip()):
                b = st.session_state.briefing
                title = b["title"] if b else stem
                queue_pending("send_email", {"to": MY_EMAIL, "subject": f"[회의록 요약] {title} ({st.session_state.meeting_date})",
                                             "body": text})
                st.rerun()


def render_tasks(ctx):
    """페이지: 내 업무 — 헤더 + [남은 업무 모두 캘린더에 추가] + 필터(추가 전/추가됨/완료) + 업무 카드"""
    tasks = st.session_state.tasks
    with st.container(key="page_tasks"):
        if not ctx["has_meeting"] or not tasks:
            with st.container(key="card_empty"):
                st.markdown('<p class="aivle-h1">내 업무</p>', unsafe_allow_html=True)
                if not ctx["has_meeting"]:
                    st.markdown(f'<p class="aivle-hint">회의록을 올리면 {USER_NAME}님께 배정된 업무가 여기에 정리돼요.</p>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<p class="aivle-hint">이 회의록에서는 {USER_NAME}님 업무를 찾지 못했어요. 다른 회의록을 올려 보세요.</p>', unsafe_allow_html=True)
                if st.button(f"{PAGES['assistant']}로 가기", key="btn_go_assistant", type="primary"):
                    go("assistant")
            return

        by_status = {"todo": [], "scheduled": [], "done": []}
        for t in tasks:
            by_status[task_status(t)].append(t)
        h1, h2 = st.columns([3, 1.6], vertical_alignment="bottom")
        h1.markdown(f'<p class="aivle-eyebrow">{esc(st.session_state.meeting_name)} · {fmt_kor_day(st.session_state.meeting_date)} 회의에서 배정</p>'
                    f'<p class="aivle-h1">내 업무 <b>{len(tasks)}건</b></p>', unsafe_allow_html=True)
        if by_status["todo"] and h2.button(f"남은 업무 모두 캘린더에 추가 ({len(by_status['todo'])}건)", key="btn_add_all", type="primary"):
            for t in by_status["todo"]:
                queue_task(t)
            st.rerun()

        # 필터
        counts = {"all": len(tasks), "todo": len(by_status["todo"]), "scheduled": len(by_status["scheduled"]), "done": len(by_status["done"])}
        names = {"all": "전체", "todo": "캘린더 추가 전", "scheduled": "추가됨", "done": "완료"}
        if st.session_state.get("task_filter") not in names:          # 예전 값(문자열 라벨)이 남아 있으면 초기화
            st.session_state.pop("task_filter", None)
        choice = st.radio("보기", list(names), format_func=lambda k: f"{names[k]} {counts[k]}", horizontal=True,
                          label_visibility="collapsed", key="task_filter")
        shown = list(tasks) if choice == "all" else by_status[choice]

        sel_id = st.session_state.selected_task                     # 대화에서 고른 업무를 맨 앞에
        shown = sorted(shown, key=lambda t: 0 if t["id"] == sel_id else 1)
        index_of = {t["id"]: i + 1 for i, t in enumerate(tasks)}
        if not shown:
            st.markdown('<p class="aivle-hint">이 조건에 맞는 업무가 없어요.</p>', unsafe_allow_html=True)

        for t in shown:
            selected = t["id"] == sel_id
            status = task_status(t)
            with st.container(key=(f"task_sel_{t['id']}" if selected else f"task_card_{t['id']}")):
                tags = ""
                if selected:
                    tags += '<span class="aivle-tag">대화에서 선택한 업무</span>'
                if t["id"] in st.session_state.drafts:
                    tags += '<span class="aivle-tag aivle-tag-p">초안 있음</span>'
                if status == "done":
                    tags += '<span class="aivle-tag aivle-tag-ok">완료</span>'
                if tags:
                    st.markdown(tags, unsafe_allow_html=True)
                c1, c2, c3 = st.columns([0.45, 3.0, 2.6], vertical_alignment="center")
                c1.markdown(f'<span class="aivle-num">{index_of[t["id"]]}</span>', unsafe_allow_html=True)
                due_html = (f'<span>{esc(task_due_label(t))}</span>' if t.get("due") else f'<span class="aivle-warn">{esc(task_due_label(t))}</span>')
                c2.markdown(f'<p class="aivle-task-title">{esc(t["title"])}</p>'
                            f'<p class="aivle-task-meta">{esc(t["detail"])} · 요청 {esc(t["requester"])} · {due_html}</p>', unsafe_allow_html=True)
                with c3:                                              # 2 x 2 버튼: [캘린더][초안] / [완료][요청]
                    r1a, r1b = st.columns(2, gap="small")
                    r2a, r2b = st.columns(2, gap="small")
                    with r1a:
                        if status == "todo":
                            if st.button("캘린더에 추가", key=f"btn_add_{t['id']}", type="primary", width="stretch"):
                                queue_task(t)
                                st.rerun()
                        elif t.get("event_id"):
                            if st.button("✓ 캘린더 보기", key=f"btn_seecal_{t['id']}", width="stretch"):
                                d = parse_iso(t["due"]) or today
                                go("calendar", cal_year=d.year, cal_month=d.month)
                        else:
                            st.markdown('<span class="aivle-done">✓ 완료</span>', unsafe_allow_html=True)
                    with r1b:
                        if st.button(f"{APP_NAME}에게 초안 맡기기" if t["id"] not in st.session_state.drafts else "초안 보기", key=f"btn_draft_{t['id']}", width="stretch"):
                            st.session_state.draft_task = t["id"]
                            st.rerun()
                    with r2a:
                        if status != "done":
                            if st.button("완료", key=f"btn_done_{t['id']}", width="stretch"):
                                mark_task_done(t, True)
                                st.toast(f"'{t['title']}' 완료로 표시했어요.")
                                st.rerun()
                        elif st.button("완료 취소", key=f"btn_undone_{t['id']}", width="stretch"):
                            mark_task_done(t, False)
                            st.rerun()
                    with r2b:
                        if st.button("협업·미팅 요청", key=f"btn_req_{t['id']}", width="stretch"):
                            open_request(task=t)
                            st.rerun()


def render_calendar(ctx):
    """페이지: 캘린더 — 월 이동/새로고침 + 눌러서 여는 월간 그리드 + 다가오는 일정 + 보낸 요청"""
    cal_y, cal_m = ctx["cal_y"], ctx["cal_m"]
    is_owner = ctx["is_owner"]
    with st.container(key="page_calendar"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small", key="cal_head"):
            st.markdown(f'<p class="aivle-h1">캘린더 <span style="font-weight:500">{cal_y}년 {cal_m}월</span></p>', unsafe_allow_html=True)
            st.space("stretch")
            if st.button("", key="btn_prev", icon=":material/chevron_left:", help="이전 달"):
                st.session_state.cal_year, st.session_state.cal_month = shift_month(cal_y, cal_m, -1)
                st.rerun()
            if st.button("오늘", key="btn_today"):
                st.session_state.cal_year, st.session_state.cal_month = today.year, today.month
                st.rerun()
            if st.button("", key="btn_next", icon=":material/chevron_right:", help="다음 달"):
                st.session_state.cal_year, st.session_state.cal_month = shift_month(cal_y, cal_m, 1)
                st.rerun()

        g, u = st.columns([2.2, 1], gap="medium")
        with g:
            with st.container(key="card_calendar"):
                st.markdown('<div class="aivle-legend">'
                            f'<span><i style="background:#5B4BE0"></i>{APP_NAME}이 추가한 업무</span>'
                            '<span><i style="background:#D1FAE5;border:1px solid #10B981"></i>캘린더의 다른 일정</span>'
                            '<span><i style="background:#fff;border:1px dashed #5B4BE0"></i>요청 대기</span>'
                            '<span><i style="background:#E2E8F0"></i>완료 / 거절</span></div>', unsafe_allow_html=True)
                dows = st.columns(7)
                for i, name in enumerate(WEEKDAY_KO):
                    dows[i].markdown(f'<p class="aivle-dow">{name}</p>', unsafe_allow_html=True)
                for week in build_month_cells(cal_y, cal_m, events_by_date(ctx["month_events"]), today.isoformat()):
                    cols = st.columns(7)
                    for i, cell in enumerate(week):
                        if cell is None:
                            continue
                        with cols[i]:
                            with st.container(key=(f"cellt_{cell['iso']}" if cell["is_today"] else f"cell_{cell['iso']}")):
                                st.markdown(f'<span class="aivle-daynum">{cell["day"]}{" 오늘" if cell["is_today"] else ""}</span>', unsafe_allow_html=True)
                                for ev in cell["chips"]:
                                    if st.button(chip_label(ev), key=f"ev{chip_style(ev)}_{cell['iso']}_{ev['id']}", help=ev["title"], wrap=False, width="stretch"):
                                        st.session_state.open_event = ev["id"]
                                        st.rerun()
                                if cell["more"]:
                                    st.markdown(f'<span class="aivle-more">+{cell["more"]}</span>', unsafe_allow_html=True)
        with u:
            with st.container(key="card_upcoming"):
                st.markdown('<p class="aivle-card-title">다가오는 일정</p>', unsafe_allow_html=True)
                upcoming = [e for e in ctx["all_events"] if today.isoformat() <= e["date"] <= (today + timedelta(days=30)).isoformat()][:8]
                if not upcoming:
                    st.markdown('<p class="aivle-hint">다가오는 일정이 없어요.</p>', unsafe_allow_html=True)
                for ev in upcoming:
                    if st.button(f"{fmt_short(ev['date'])} · {chip_label(ev, 40)}" + (f" · {ev['start_time']}" if ev.get("start_time") else ""),
                                 key=f"up_{ev['id']}", wrap=False, width="stretch"):
                        st.session_state.open_event = ev["id"]
                        st.rerun()
                if is_owner and st.button("내 업무로 가기", key="btn_go_tasks"):
                    go("tasks")

            if is_owner:
                sent_reqs = [e for e in ctx["all_events"] if e.get("kind") == "request" and e.get("from") == USER_NAME]
                with st.container(key="card_sent"):
                    st.markdown('<p class="aivle-card-title">보낸 요청</p>', unsafe_allow_html=True)
                    if not sent_reqs:
                        st.markdown('<p class="aivle-hint">보낸 요청이 없어요.</p>', unsafe_allow_html=True)
                    for ev in sent_reqs:
                        tag = {"pending": "대기", "accepted": "확정", "rejected": "거절됨"}.get(ev.get("status"), "")
                        if st.button(f"[{tag}] {ev.get('request_type')} · {ev.get('subject')} → {', '.join(ev.get('to') or [])} · {fmt_short(ev['date'])} {ev.get('start_time') or ''}",
                                     key=f"sent_{ev['id']}", wrap=False, width="stretch"):
                            st.session_state.open_event = ev["id"]
                            st.rerun()


def render_requests(ctx):
    """페이지(팀원 보기 모드): 받은 요청 — 수락 / 거절(이유 필수)"""
    me = st.session_state.view_as
    mine = [e for e in ctx["all_events"] if e.get("kind") == "request" and me in (e.get("to") or [])]
    pending = [e for e in mine if e.get("status") == "pending"]
    decided = [e for e in mine if e.get("status") != "pending"]
    focus = st.session_state.focus_request
    pending = sorted(pending, key=lambda e: 0 if e["id"] == focus else 1)

    st.markdown(f'<p class="aivle-eyebrow">{esc(me)} 화면 · {USER_NAME}가 보낸 요청</p><p class="aivle-h1">받은 요청 <b>{len(pending)}건</b></p>',
                unsafe_allow_html=True)
    if not pending:
        with st.container(key="card_empty"):
            st.markdown(f'<p class="aivle-hint">처리할 요청이 없어요. {USER_NAME} 화면에서 \'협업·미팅 요청\'을 보내면 여기에 나타나요.</p>', unsafe_allow_html=True)

    for ev in pending:
        with st.container(key=(f"req_focus_{ev['id']}" if ev["id"] == focus else f"req_{ev['id']}")):
            if ev["id"] == focus:
                st.markdown('<span class="aivle-tag aivle-tag-p">메일 링크로 열린 요청</span>', unsafe_allow_html=True)
            st.markdown(f'<p class="aivle-task-title">{esc(ev.get("request_type"))} · {esc(ev.get("subject"))}</p>'
                        f'<p class="aivle-task-meta">보낸 사람 {esc(ev.get("from"))} · {esc(fmt_when(ev))}</p>', unsafe_allow_html=True)
            dlg_row("메시지", ev.get("message") or "")
            if st.session_state.reject_for == ev["id"]:
                reason = st.text_area("거절 이유 (필수)", key=f"reason_{ev['id']}", placeholder="예: 그 시간에 외부 미팅이 있어요. 금요일 오후는 어떨까요?")
                c1, c2 = right_row(2)
                if c1.button("거절 확정", key=f"btn_reject_ok_{ev['id']}", type="primary"):
                    try:
                        decide_request(ev, "rejected", me, reason)
                        st.session_state.reject_for = None
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
                if c2.button("돌아가기", key=f"btn_reject_back_{ev['id']}"):
                    st.session_state.reject_for = None
                    st.rerun()
            else:
                c1, c2 = right_row(2)
                if c1.button("수락", key=f"btn_accept_{ev['id']}", type="primary"):
                    decide_request(ev, "accepted", me)
                    st.rerun()
                if c2.button("거절", key=f"btn_reject_{ev['id']}"):
                    st.session_state.reject_for = ev["id"]
                    st.rerun()

    if decided:
        st.markdown('<p class="aivle-strong" style="margin-top:16px">처리한 요청</p>', unsafe_allow_html=True)
        for ev in decided:
            tag = "aivle-tag-ok" if ev.get("status") == "accepted" else "aivle-tag-x"
            label = "확정" if ev.get("status") == "accepted" else "거절됨"
            st.markdown(f'<p class="aivle-task-meta"><span class="aivle-tag {tag}">{label}</span>{esc(ev.get("request_type"))} · {esc(ev.get("subject"))} · {esc(fmt_when(ev))}'
                        + (f' · 이유: {esc(ev.get("reason"))}' if ev.get("reason") else "") + "</p>", unsafe_allow_html=True)


def handle_query_params():
    """메일 링크 ?req=<id>&as=<이름> 로 열면 그 팀원 화면에서 해당 요청을 먼저 보여준다"""
    if st.session_state.qp_handled:
        return
    st.session_state.qp_handled = True
    try:
        req, as_name = st.query_params.get("req"), st.query_params.get("as")
    except Exception:
        return
    if req and as_name in TEAMMATES:
        st.session_state.view_as = as_name
        st.session_state.page = "requests"
        st.session_state.focus_request = req


def notify_status_changes(ctx):
    """김 대리 화면: 보낸 요청의 상태가 바뀌었으면 토스트"""
    seen = st.session_state.req_status_seen
    for ev in ctx["all_events"]:
        if ev.get("kind") != "request" or ev.get("from") != USER_NAME:
            continue
        prev = seen.get(ev["id"])
        if prev is not None and prev != ev.get("status"):
            verb = {"accepted": "수락", "rejected": "거절"}.get(ev.get("status"), "변경")
            st.toast(f"{ev.get('decided_by') or '팀원'}님이 '{ev.get('subject')}' 요청을 {verb}했어요.")
        seen[ev["id"]] = ev.get("status")


def main():
    handle_query_params()
    restore_task_statuses()
    ctx = build_context()
    render_sidebar(ctx)
    if ctx["is_owner"]:
        notify_status_changes(ctx)
    if not (st.session_state.pending_actions or st.session_state.request_form or st.session_state.draft_task or st.session_state.open_event):
        render_notice()                               # 다이얼로그가 떠 있으면 안내는 그 안에서
    page = st.session_state.page
    if not ctx["is_owner"] and page not in ("requests", "calendar"):
        page = st.session_state.page = "requests"
    if page == "summary":
        render_summary(ctx)
    elif page == "tasks":
        render_tasks(ctx)
    elif page == "calendar":
        render_calendar(ctx)
    elif page == "requests":
        render_requests(ctx)
    else:
        render_assistant(ctx)
    render_dialogs()


main()
