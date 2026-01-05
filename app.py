import streamlit as st
import json
import pandas as pd
from streamlit_gsheets import GSheetsConnection
from PIL import Image 
import io
from fpdf import FPDF 

# ==========================================
# 0. 網頁基礎設定 (改用這裡設定圖示)
# ==========================================
# iPhone 會嘗試抓取這裡設定的 page_icon
# 請確保你的資料夾裡有 'ios_icon.png' (那個有底色、不透明的版本)
try:
    # 直接讀取 ios_icon.png 當作全站圖示
    icon_image = Image.open("ios_icon.png") 
    st.set_page_config(
        page_title="升等考 法學知識與英文", 
        page_icon=icon_image,  # <--- 關鍵：這裡餵給它高品質圖片
        layout="wide"
    )
except FileNotFoundError:
    # 萬一找不到圖片的備用方案
    st.set_page_config(page_title="升等考 法學知識與英文", page_icon="🚒", layout="wide")

# (注意：原本那個 0.5 def set_apple_icon... 的整段程式碼請直接刪除，因為沒用)

# ==========================================
# 1. Google Sheets 資料庫功能
# ==========================================
def get_user_data(username):
    """從 Google Sheet 讀取該使用者的資料"""
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
            
            fav_set = set(json.loads(fav_str)) if fav_str and fav_str != 'nan' else set()
            mis_set = set(json.loads(mis_str)) if mis_str and mis_str != 'nan' else set()
            return fav_set, mis_set
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
# 2. 登入驗證功能
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
                
                with st.spinner("☁️ 正在從雲端下載您的進度..."):
                    f_data, m_data = get_user_data(selected_user)
                    st.session_state['favorites'] = f_data
                    st.session_state['mistakes'] = m_data
                
                st.rerun()
            else:
                st.error(f"❌ 密碼錯誤")
    return False

if not check_password():
    st.stop()

# ==========================================
# 3. 核心邏輯與載入資料
# ==========================================

if 'favorites' not in st.session_state:
    st.session_state['favorites'] = set()
if 'mistakes' not in st.session_state:
    st.session_state['mistakes'] = set()

@st.cache_data
def load_questions():
    with open('questions.json', 'r', encoding='utf-8') as f:
        return json.load(f)

try:
    all_questions = load_questions()
except FileNotFoundError:
    st.error("❌ 找不到 questions.json 檔案！")
    st.stop()

# ==========================================
# 4. PDF 匯出功能函數
# ==========================================
def create_pdf(questions, title):
    pdf = FPDF()
    pdf.add_page()
    
    try:
        pdf.add_font('ChineseFont', '', 'font.ttf')
        pdf.set_font('ChineseFont', '', 12)
    except:
        return None

    # 標題
    pdf.set_font_size(16)
    pdf.cell(0, 10, title, ln=True, align='C')
    pdf.ln(5)
    
    # 內容設定
    pdf.set_font_size(11)
    
    for idx, q in enumerate(questions):
        # 1. 檢查剩餘空間，如果快到底部了就換頁 (預防題目被切斷)
        if pdf.get_y() > 250:
            pdf.add_page()

        # 2. 寫入題目
        q_year = q.get('year', '')
        q_id = str(q.get('id', ''))
        q_content = q.get('question', '')
        question_text = f"{idx + 1}. [{q_year}#{q_id[-2:]}] {q_content}"
        pdf.multi_cell(0, 7, question_text) # 降低行高至 7
        
        # 3. 逐一寫入選項 (解決版型跑掉的關鍵)
        options = q.get('options', [])
        pdf.ln(1) # 題目與選項間微小間隔
        for opt in options:
            pdf.set_x(15) # 左側縮排 15mm
            # 使用 multi_cell 確保單個選項太長時也會自動在縮排範圍內換行
            pdf.multi_cell(0, 7, opt) 
        
        # 4. 寫入正解 (放在選項下方，稍微留白)
        pdf.ln(1)
        pdf.set_x(15)
        pdf.set_text_color(150, 150, 150) # 灰色
        ans = q.get('answer', '')
        pdf.cell(0, 7, f"👉 正解: ({ans})", ln=True)
        pdf.set_text_color(0, 0, 0) # 恢復黑色
        
        pdf.ln(5) # 題與題之間的間距
        pdf.line(10, pdf.get_y(), 200, pdf.get_y()) # 畫一條淡淡的分隔線 (可選)
        pdf.ln(5)

    return bytes(pdf.output())

# ==========================================
# 5. 側邊欄與篩選邏輯
# ==========================================
st.sidebar.header(f"👤 {st.session_state['username']} 的戰情室")

if st.sidebar.button("💾 手動雲端存檔"):
    save_user_data(st.session_state['username'], st.session_state['favorites'], st.session_state['mistakes'])
    st.sidebar.success("✅ 已上傳雲端！")

keyword = st.sidebar.text_input("🔍 搜尋關鍵字")
st.sidebar.markdown("---")

# --- 修正版 Radio 按鈕邏輯 (解決跳頁問題) ---
MODE_NORMAL = "normal"
MODE_FAV = "fav"
MODE_MIS = "mis"

def format_mode_option(option_key):
    if option_key == MODE_NORMAL:
        return "一般刷題"
    elif option_key == MODE_FAV:
        return f"⭐ 題目收藏 ({len(st.session_state['favorites'])})"
    elif option_key == MODE_MIS:
        return f"❌ 錯題複習 ({len(st.session_state['mistakes'])})"
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
    st.session_state.view_mode = MODE_NORMAL

# 建立 Radio
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

# 科目篩選
subject_list = list(set([q['subject'] for q in all_questions]))
if subject_list:
    selected_subject = st.sidebar.radio("科目", subject_list)
else:
    selected_subject = "無資料"

# 年份篩選
subject_data = [q for q in all_questions if q['subject'] == selected_subject]
years_available = sorted(list(set([q['year'] for q in subject_data])), reverse=True)
selected_years = [y for y in years_available if st.sidebar.checkbox(f"{y} 年", value=True)]

# 資料池篩選
current_pool = []
for q in all_questions:
    if q['subject'] != selected_subject: continue
    if keyword and keyword not in q['question']: continue
    
    # 模式過濾
    if mode == MODE_FAV and q['id'] not in st.session_state['favorites']: continue
    if mode == MODE_MIS and q['id'] not in st.session_state['mistakes']: continue
    
    if q['year'] not in selected_years: continue
    current_pool.append(q)

# 分類篩選
cat_counts = {q['category']: 0 for q in subject_data}
for q in current_pool:
    cat_counts[q['category']] = cat_counts.get(q['category'], 0) + 1

categories = sorted(list(set([q['category'] for q in subject_data])))
categories.insert(0, "全部")

selected_category = st.sidebar.radio("領域", categories, format_func=lambda x: f"{x} ({cat_counts.get(x,0)})" if x != "全部" else f"全部 ({len(current_pool)})")

# 細項篩選
selected_sub_cat = "全部"
if selected_category != "全部":
    sub_pool = [q for q in current_pool if q['category'] == selected_category]
    sub_counts = {}
    for q in sub_pool:
        sub_counts[q['sub_category']] = sub_counts.get(q['sub_category'], 0) + 1
    
    base_sub_cats = sorted(list(set([q['sub_category'] for q in subject_data if q['category'] == selected_category])))
    base_sub_cats.insert(0, "全部")
    selected_sub_cat = st.sidebar.radio("細項", base_sub_cats, format_func=lambda x: f"{x} ({sub_counts.get(x,0)})" if x != "全部" else f"全部 ({len(sub_pool)})")

# 最終篩選結果
final_questions = [q for q in current_pool if (selected_category == "全部" or q['category'] == selected_category) and (selected_sub_cat == "全部" or q['sub_category'] == selected_sub_cat)]

# ==========================================
# 6. 主畫面顯示與 PDF 按鈕
# ==========================================
st.title(f"🔥 {selected_subject} 刷題區")
st.write(f"題目數：{len(final_questions)}")

# --- PDF 下載按鈕區塊 ---
if final_questions:
    col_dl1, col_dl2 = st.columns([0.7, 0.3])
    with col_dl2:
        # 設定標題名稱
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
                    st.download_button(
                        label="📥 點擊下載 PDF",
                        data=pdf_bytes,
                        file_name=f"{pdf_title}.pdf",
                        mime="application/pdf"
                    )
                else:
                    st.error("❌ 錯誤：找不到字型檔 (font.ttf)，無法生成 PDF。")

st.markdown("---")

# 顯示提示訊息
if not final_questions:
    if mode == MODE_MIS:
        st.success("🎉 太棒了！目前的篩選範圍內沒有錯題！")
    elif mode == MODE_FAV:
        st.warning("⚠️ 你還沒有收藏任何題目喔！")
    else:
        st.warning("⚠️ 沒有符合條件的題目")

# 顯示題目迴圈
for q in final_questions:
    q_label = f"{q['year']}#{str(q['id'])[-2:]}"
    
    with st.container():
        col_star, col_q = st.columns([0.08, 0.92])
        
        with col_star:
            is_fav = q['id'] in st.session_state['favorites']
            btn_label = "⭐" if is_fav else "☆"
            # 注意：這裡使用 key 確保按鈕獨立
            if st.button(btn_label, key=f"fav_{q['id']}"):
                if is_fav:
                    st.session_state['favorites'].discard(q['id'])
                else:
                    st.session_state['favorites'].add(q['id'])
                
                save_user_data(st.session_state['username'], st.session_state['favorites'], st.session_state['mistakes'])
                st.rerun()

        with col_q:
            st.markdown(f"### **[{q_label}]** {q['question']}")
            
            # 選項顯示
            user_answer = st.radio("選項", q['options'], key=f"q_{q['id']}", label_visibility="collapsed", index=None)
            
            if user_answer:
                # 取得選項的第一個字元 (A, B, C, D)
                ans_char = user_answer.replace("(", "").replace(")", "").replace(".", "").strip()[0]
                
                if ans_char == q['answer']:
                    st.success(f"✅ 正確！")
                    
                    # 錯題模式下，答對自動移除並重整
                    if mode == MODE_MIS and q['id'] in st.session_state['mistakes']:
                        st.session_state['mistakes'].discard(q['id'])
                        save_user_data(st.session_state['username'], st.session_state['favorites'], st.session_state['mistakes'])
                        st.rerun()
                else:
                    st.error(f"❌ 錯誤，答案是 {q['answer']}")
                    # 答錯自動加入錯題
                    if q['id'] not in st.session_state['mistakes']:
                        st.session_state['mistakes'].add(q['id'])
                        save_user_data(st.session_state['username'], st.session_state['favorites'], st.session_state['mistakes'])
                
                with st.expander("查看詳解"):
                    st.info(q['explanation'])
        st.markdown("---")