import streamlit as st
import json
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from PIL import Image 
import io
from fpdf import FPDF 

# ==========================================
# 0. 網頁基礎設定
# ==========================================
try:
    icon_image = Image.open("ios_icon.png") 
    st.set_page_config(
        page_title="升等考 法學知識與英文", 
        page_icon=icon_image, 
        layout="wide"
    )
except:
    st.set_page_config(page_title="升等考 法學知識與英文", page_icon="⚖️", layout="wide")

# ==========================================
# 1. 核心載入資料 (先讀取題庫，供後續比對使用)
# ==========================================
@st.cache_data
def load_questions():
    with open('questions.json', 'r', encoding='utf-8') as f:
        return json.load(f)

try:
    all_questions = load_questions()
    # 建立所有合法 ID 的集合，用於後續過濾幽靈紀錄
    ALL_VALID_IDS = {q['id'] for q in all_questions}
except FileNotFoundError:
    st.error("❌ 找不到 questions.json 檔案！")
    st.stop()

# ==========================================
# 2. Google Sheets 資料庫功能 (包含一勞永逸過濾邏輯)
# ==========================================
def get_user_data(username):
    """從 Google Sheet 讀取資料，並自動剔除不存在於題庫中的舊 ID"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(ttl=0)
        
        expected_cols = ['Username', 'Favorites', 'Mistakes']
        if df.empty or not all(col in df.columns for col in expected_cols):
            df = pd.DataFrame(columns=expected_cols)

        user_row = df[df['Username'] == username]
        
        if not user_row.empty:
            fav_str = str(user_row.iloc[0]['Favorites'])
            mis_str = str(user_row.iloc[0]['Mistakes'])
            
            # 解析原始 JSON 字串
            raw_favs = set(json.loads(fav_str)) if fav_str and fav_str != 'nan' else set()
            raw_mists = set(json.loads(mis_str)) if mis_str and mis_str != 'nan' else set()
            
            # --- 一勞永逸的關鍵：交集過濾 (Intersection) ---
            # 只保留那些「目前題庫中確實存在」的 ID
            clean_favs = raw_favs.intersection(ALL_VALID_IDS)
            clean_mists = raw_mists.intersection(ALL_VALID_IDS)
            
            # 如果發現有髒資料被濾掉了，自動同步回雲端，下次就不會再出現
            if len(clean_favs) != len(raw_favs) or len(clean_mists) != len(raw_mists):
                save_user_data(username, clean_favs, clean_mists)
                
            return clean_favs, clean_mists
        else:
            return set(), set()
    except Exception as e:
        st.error(f"連線讀取失敗：{e}")
        return set(), set()

def save_user_data(username, fav_set, mis_set):
    """將資料寫回 Google Sheet"""
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(ttl=0)
        
        fav_json = json.dumps(list(fav_set))
        mis_json = json.dumps(list(mis_set))
        
        if username in df['Username'].values:
            df.loc[df['Username'] == username, 'Favorites'] = fav_json
            df.loc[df['Username'] == username, 'Mistakes'] = mis_json
        else:
            new_row = pd.DataFrame({
                'Username': [username], 
                'Favorites': [fav_json], 
                'Mistakes': [mis_json]
            })
            df = pd.concat([df, new_row], ignore_index=True)
            
        conn.update(data=df)
        
    except Exception as e:
        st.warning(f"自動存檔失敗：{e}")

# ==========================================
# 3. 登入驗證功能
# ==========================================
def check_password():
    if st.session_state.get("password_correct", False):
        return True

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.header("🔒 升等考 法學知識與英文 - 雲端版")
        
        try:
            user_list = list(st.secrets["passwords"].keys())
        except:
            st.error("尚未設定 Secrets，請檢查 .streamlit/secrets.toml")
            st.stop()

        selected_user = st.selectbox("請選擇登入人員", user_list)
        password_input = st.text_input("請輸入密碼", type="password")
        
        if st.button("登入"):
            correct_password = st.secrets["passwords"][selected_user]
            if password_input == correct_password:
                st.session_state["password_correct"] = True
                st.session_state["username"] = selected_user
                
                with st.spinner("☁️ 正在從雲端下載您的進度並自動優化紀錄..."):
                    # 這裡會觸發剛才寫的自動清洗邏輯
                    f_data, m_data = get_user_data(selected_user)
                    st.session_state['favorites'] = f_data
                    st.session_state['mistakes'] = m_data
                
                st.rerun()
            else:
                st.error(f"❌ 密碼錯誤")
    return False

if not check_password():
    st.stop()

# --- 初始化狀態 ---
if 'favorites' not in st.session_state:
    st.session_state['favorites'] = set()
if 'mistakes' not in st.session_state:
    st.session_state['mistakes'] = set()

# ==========================================
# 4. PDF 匯出功能函數
# ==========================================
def create_pdf(questions, title):
    pdf = FPDF()
    pdf.add_page()
    
    try:
        pdf.add_font('ChineseFont', '', 'font.ttf')
        pdf.set_font('ChineseFont', '', 12)
    except Exception as e:
        st.error(f"❌ PDF 字型載入失敗: {e}")
        return None

    try:
        pdf.set_font_size(16)
        pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT", align='C')
        pdf.ln(5)
        
        pdf.set_font_size(11)
        for idx, q in enumerate(questions):
            if pdf.get_y() > 250:
                pdf.add_page()

            q_text = f"{idx + 1}. [{q.get('year')}#{str(q.get('id'))[-2:]}] {q.get('question')}"
            pdf.multi_cell(0, 7, q_text, new_x="LMARGIN", new_y="NEXT")
            
            pdf.ln(1)
            for opt in q.get('options', []):
                pdf.set_x(15)
                pdf.multi_cell(0, 7, opt, new_x="LMARGIN", new_y="NEXT")
            
            pdf.ln(1)
            pdf.set_x(15)
            pdf.set_text_color(150, 150, 150)
            pdf.cell(0, 7, f"👉 正解: ({q.get('answer')})", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            
            pdf.ln(5)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(5)
            
        return bytes(pdf.output()) 
        
    except Exception as e:
        st.error(f"❌ PDF 排版出錯: {e}")
        return None

# ==========================================
# 5. 側邊欄與篩選邏輯
# ==========================================
st.sidebar.header(f"👤 {st.session_state['username']} 的戰情室")

if st.sidebar.button("💾 手動雲端存檔"):
    save_user_data(st.session_state['username'], st.session_state['favorites'], st.session_state['mistakes'])
    st.sidebar.success("✅ 已強制上傳雲端！")

keyword = st.sidebar.text_input("🔍 搜尋關鍵字")
st.sidebar.markdown("---")

MODE_NORMAL = "normal"
MODE_FAV = "fav"
MODE_MIS = "mis"

def format_mode_option(option_key):
    if option_key == MODE_NORMAL: return "一般刷題"
    elif option_key == MODE_FAV: return f"⭐ 題目收藏 ({len(st.session_state['favorites'])})"
    elif option_key == MODE_MIS: return f"❌ 錯題複習 ({len(st.session_state['mistakes'])})"
    return option_key

if 'view_mode' not in st.session_state:
    st.session_state.view_mode = MODE_NORMAL

def on_mode_change():
    st.session_state.view_mode = st.session_state.mode_selector_ui

options = [MODE_NORMAL, MODE_FAV, MODE_MIS]
try:
    current_index = options.index(st.session_state.view_mode)
except ValueError:
    current_index = 0

mode_selection = st.sidebar.radio(
    "模式", 
    options, 
    format_func=format_mode_option,
    index=current_index,      
    key="mode_selector_ui",    
    on_change=on_mode_change   
)
mode = st.session_state.view_mode

st.sidebar.markdown("---")

# 科目與年份篩選
subject_list = list(set([q['subject'] for q in all_questions]))
selected_subject = st.sidebar.radio("科目", subject_list) if subject_list else "無資料"

subject_data = [q for q in all_questions if q['subject'] == selected_subject]
years_available = sorted(list(set([q['year'] for q in subject_data])), reverse=True)
selected_years = [y for y in years_available if st.sidebar.checkbox(f"{y} 年", value=True)]

# ==========================================
# 6. 篩選邏輯執行
# ==========================================
current_pool = []
for q in all_questions:
    if q['subject'] != selected_subject: continue
    if q['year'] not in selected_years: continue
    if keyword and keyword not in q['question']: continue
    if mode == MODE_FAV and q['id'] not in st.session_state['favorites']: continue
    if mode == MODE_MIS and q['id'] not in st.session_state['mistakes']: continue
    current_pool.append(q)

cat_counts = {cat: 0 for cat in set([q.get('category', '未分類') for q in current_pool])}
for q in current_pool:
    cat = q.get('category', '未分類')
    cat_counts[cat] += 1

categories = sorted(list(cat_counts.keys()))
categories.insert(0, "全部")

selected_category = st.sidebar.radio(
    "領域", 
    categories, 
    format_func=lambda x: f"{x} ({cat_counts.get(x, 0)})" if x != "全部" else f"全部 ({len(current_pool)})"
)

final_questions = current_pool if selected_category == "全部" else [q for q in current_pool if q.get('category') == selected_category]

# ==========================================
# 7. 主畫面顯示
# ==========================================
st.title(f"🔥 {selected_subject} 刷題區")
st.write(f"題目數：{len(final_questions)}")

if final_questions:
    col_dl1, col_dl2 = st.columns([0.7, 0.3])
    with col_dl2:
        if mode == MODE_FAV:
            pdf_title = f"【收藏題本】{st.session_state['username']} - {selected_subject}"
            btn_label = "🖨️ 匯出收藏題目 (PDF)"
        elif mode == MODE_MIS:
            pdf_title = f"【錯題本】{st.session_state['username']} - {selected_subject}"
            btn_label = "🖨️ 匯出錯題複習 (PDF)"
        else:
            pdf_title = f"【刷題本】{selected_subject} 精選"
            btn_label = "🖨️ 匯出當前題目 (PDF)"

        if st.button(btn_label, use_container_width=True):
            with st.spinner("正在排版印刷中..."):
                pdf_bytes = create_pdf(final_questions, pdf_title)
                if pdf_bytes:
                    st.download_button(label="📥 點擊下載 PDF", data=pdf_bytes, file_name=f"{pdf_title}.pdf", mime="application/pdf")
                else:
                    st.error("❌ 錯誤：找不到字型檔 (font.ttf)。")

st.markdown("---")

if not final_questions:
    if mode == MODE_MIS: st.success("🎉 太棒了！目前的篩選範圍內沒有錯題！")
    elif mode == MODE_FAV: st.warning("⚠️ 你還沒有收藏任何題目喔！")
    else: st.warning("⚠️ 沒有符合條件的題目")

for q in final_questions:
    q_label = f"{q['year']}#{str(q['id'])[-2:]}"
    with st.container():
        col_star, col_q = st.columns([0.08, 0.92])
        with col_star:
            is_fav = q['id'] in st.session_state['favorites']
            if st.button("⭐" if is_fav else "☆", key=f"fav_{q['id']}"):
                if is_fav: st.session_state['favorites'].discard(q['id'])
                else: st.session_state['favorites'].add(q['id'])
                save_user_data(st.session_state['username'], st.session_state['favorites'], st.session_state['mistakes'])
                st.rerun()

        with col_q:
            st.markdown(f"### **[{q_label}]** {q['question']}")
            user_answer = st.radio("選項", q['options'], key=f"q_{q['id']}", label_visibility="collapsed", index=None)
            
            if user_answer:
                ans_char = user_answer.replace("(", "").replace(")", "").replace(".", "").strip()[0]
                if ans_char == q['answer']:
                    st.success(f"✅ 正確！")
                    if mode == MODE_MIS and q['id'] in st.session_state['mistakes']:
                        st.session_state['mistakes'].discard(q['id'])
                        save_user_data(st.session_state['username'], st.session_state['favorites'], st.session_state['mistakes'])
                        st.rerun()
                else:
                    st.error(f"❌ 錯誤，答案是 {q['answer']}")
                    if q['id'] not in st.session_state['mistakes']:
                        st.session_state['mistakes'].add(q['id'])
                        save_user_data(st.session_state['username'], st.session_state['favorites'], st.session_state['mistakes'])
                with st.expander("查看詳解"):
                    st.info(q['explanation'])
        st.markdown("---")