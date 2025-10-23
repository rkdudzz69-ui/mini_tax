import io
import re
import pandas as pd
import streamlit as st

# (선택) OpenAI SDK
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # 설치 안 되어 있으면 안내만

# ==============================
# 공통 설정
# ==============================
st.set_page_config(page_title="사업자 파일 업로드하기", layout="wide")
st.title("사업자 파일 업로드하기")

# ==============================
# 예시 데이터 (업로드 없을 때 사용)
# ==============================
SAMPLE_DATA = {
    "상호": ["A상사", "B무역", "C식당", "D전자", "E상점", "F기업", "G상회"],
    "사업자번호": ["111-11-11111", "222-22-22222", "333-33-33333", "444-44-44444", "555-55-55555", "666-66-66666", "777-77-77777"],
    "대표자": ["홍길동", "김철수", "이영희", "박민수", "최유진", "정다혜", "오성민"],
    "주민번호": ["800101-1234567", "820202-2345678", "830303-3456789", "840404-4567890", "850505-5678901", "860606-6789012", "870707-7890123"],
    "사업자상태": ["계속사업자", "폐업", "폐업", "계속사업자", "폐업", "계속사업자", "계속사업자"],
    "폐업일자": ["", "2020-03-01", "2021-05-10", "", "2023-01-30", "", ""],
}

# ==============================
# 유틸 함수
# ==============================
@st.cache_data(show_spinner=False)
def load_df_from_file(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith(".csv"):
        content = file.read()
        for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
            try:
                return pd.read_csv(io.BytesIO(content), encoding=enc)
            except Exception:
                continue
        return pd.read_csv(io.BytesIO(content), encoding_errors="ignore")
    else:
        return pd.read_excel(file)

def normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    for c in out.columns:
        if out[c].dtype == "object":
            out[c] = out[c].astype(str).str.strip()
    return out

def digits_only(s: str) -> str:
    return re.sub(r"[^0-9]", "", s or "")

def norm_text(s: str) -> str:
    return (s or "").strip().lower()

# ==============================
# 데이터 로드
# ==============================
file = st.file_uploader("사업내역 파일 업로드 (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])
if file:
    df = load_df_from_file(file)
else:
    st.info("업로드가 없어서 예시 데이터를 사용 중이야. 실제 파일을 올리면 그걸로 분석해!")
    df = pd.DataFrame(SAMPLE_DATA)

df = normalize_cols(df)

# 필수 컬럼 확인
required = {"상호", "사업자번호", "대표자", "주민번호", "사업자상태"}
missing = [c for c in required if c not in df.columns]
if missing:
    st.error(f"필수 컬럼이 없어요: {', '.join(missing)}")
    st.stop()

# 폐업일자 파싱
if "폐업일자" in df.columns:
    df["폐업일자"] = df["폐업일자"].replace({"": pd.NA})
    df["폐업일자(파싱)"] = pd.to_datetime(df["폐업일자"], errors="coerce")
else:
    df["폐업일자"] = pd.NA
    df["폐업일자(파싱)"] = pd.NaT

# ==============================
# 사이드바 카테고리
# ==============================
st.sidebar.header("카테고리")
page = st.sidebar.radio(
    "보기 선택",
    ["사업자 조회", "전체 폐업자 조회", "연도별 폐업자 수 통계", "동일 사업자(대표자/주민번호) 내역", "🤖 챗봇"],
    index=0
)

# ==============================
# 1) 사업자 조회
# ==============================
def render_search(df: pd.DataFrame):
    st.markdown("## 🔎 사업자 조회")
    st.caption("여러 명/여러 조건을 한 번에 검색할 수 있어요. 각 입력칸은 상호·대표자·사업자번호·주민번호에 부분 일치로 매칭됩니다.")

    # 매칭 방식
    match_mode = st.radio("매칭 방식 (각 입력칸에 적용)", ["부분 포함(AND)", "부분 포함(OR)"], horizontal=True)

    # 세션 초기화
    if "multi_queries" not in st.session_state:
        st.session_state.multi_queries = [""]

    # --- 버튼 스타일 (가로로 넓게, 줄바꿈 금지) ---
    st.markdown("""
        <style>
        div.stButton > button {
            width: 120px !important;
            height: 40px !important;
            font-size: 16px !important;
            font-weight: 600 !important;
            white-space: nowrap !important;  /* ✅ 줄바꿈 방지 */
            color: #222 !important;
            background-color: #FFFFFF !important;
            border: 1px solid #CCCCCC !important;
            border-radius: 8px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }
        div.stButton { display: flex !important; justify-content: center !important; }
        </style>
    """, unsafe_allow_html=True)

    # 버튼
    st.caption("입력칸 추가 / 삭제")
    col_add, spacer, col_del, _ = st.columns([0.2, 0.05, 0.2, 4])
    with col_add:
        if st.button("+행추가", key="add_query", use_container_width=True):
            st.session_state.multi_queries.append("")
    with col_del:
        if st.button("-행삭제", key="del_query", use_container_width=True) and len(st.session_state.multi_queries) > 1:
            st.session_state.multi_queries.pop()

    # 입력칸 (가로 폭 줄임)
    new_vals = []
    for i, val in enumerate(st.session_state.multi_queries):
        st.markdown(f"**검색어 #{i+1}**")
        c_in, _ = st.columns([1, 2])
        with c_in:
            new_vals.append(
                st.text_input(
                    label="",
                    value=val,
                    placeholder="예) 홍길동 1111111111 8001011234567",
                    key=f"query_input_{i}",
                )
            )
    st.session_state.multi_queries = new_vals

    # 검색 로직
    work = df.copy()
    work["_bnum_d"] = work["사업자번호"].apply(digits_only)
    work["_rrn_d"] = work["주민번호"].apply(digits_only)

    def mask_for_one_query(q: str):
        q = (q or "").strip()
        if not q:
            return pd.Series([False] * len(work), index=work.index)
        terms = [t.strip() for t in q.split() if t.strip()]

        def row_match(row):
            hay_text = " ".join([
                norm_text(row.get("상호", "")),
                norm_text(row.get("대표자", "")),
                norm_text(row.get("사업자번호", "")),
                norm_text(row.get("주민번호", "")),
            ])
            hay_digits = " ".join([row["_bnum_d"], row["_rrn_d"]])

            def contains(term):
                t_txt = term.lower()
                t_dig = digits_only(term)
                return (t_txt in hay_text) or (t_dig and t_dig in hay_digits)

            checks = [contains(t) for t in terms]
            return all(checks) if match_mode.startswith("부분 포함(AND)") else any(checks)

        return work.apply(row_match, axis=1)

    # 결과 결합
    masks = [mask_for_one_query(q) for q in st.session_state.multi_queries]
    if any(m.any() for m in masks):
        final_mask = pd.Series(False, index=work.index)
        for m in masks:
            final_mask |= m
        result = work.loc[final_mask].drop(columns=["_bnum_d", "_rrn_d"], errors="ignore")
    else:
        result = work.iloc[0:0]

    # 결과 표시
    c1, c2 = st.columns(2)
    c1.metric("업로드 행 수", len(df))
    c2.metric("검색 결과 수", len(result))

    if all((q.strip() == "") for q in st.session_state.multi_queries):
        st.info("검색어를 하나 이상 입력해 주세요. 여러 명을 찾으려면 ‘+행추가’를 눌러 주세요.")
    elif result.empty:
        st.warning("검색 결과가 없습니다.")

    cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"]
    cols = [c for c in cols if c in result.columns]
    st.dataframe(result.reindex(columns=cols), use_container_width=True)

    if not result.empty:
        st.download_button(
            "⬇️ 검색 결과 CSV 다운로드",
            data=result.reindex(columns=cols).to_csv(index=False).encode("utf-8-sig"),
            file_name="사업자_조회_결과.csv",
            mime="text/csv"
        )

# ==============================
# (다른 카테고리: 폐업자 조회, 통계, 중복, 챗봇)
# ==============================
# 그대로 유지 – 위 코드와 동일하게 기존에 쓰던 걸 두면 돼 (너무 길어 생략)
# render_closed_list(), render_closed_by_year(), render_duplicates(), render_chatbot()

# ==============================
# 라우팅
# ==============================
if page == "사업자 조회":
    render_search(df)
elif page == "전체 폐업자 조회":
    st.write("📋 전체 폐업자 조회 페이지 (이전 코드 그대로)")
elif page == "연도별 폐업자 수 통계":
    st.write("📈 연도별 통계 페이지 (이전 코드 그대로)")
elif page == "동일 사업자(대표자/주민번호) 내역":
    st.write("👥 동일 사업자 내역 페이지 (이전 코드 그대로)")
else:
    st.write("🤖 챗봇 페이지 (이전 코드 그대로)")
