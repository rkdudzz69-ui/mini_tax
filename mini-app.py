import io
import pandas as pd
import streamlit as st

# -------------------------
# 기본 설정
# -------------------------
st.set_page_config(page_title="전체 폐업자 현황", layout="wide")

st.title("전체 폐업자 현황")
st.caption("엑셀을 업로드하면 '사업자상태'가 '폐업'인 행만 추출됩니다.)

# -------------------------
# 예시 데이터 (업로드 없을 때 사용)
# -------------------------
SAMPLE_DATA = {
    "상호": ["A상사", "B무역", "C식당", "D전자", "E상점", "F기업", "G상회"],
    "사업자번호": ["111-11-11111", "222-22-22222", "333-33-33333", "444-44-44444", "555-55-55555", "666-66-66666", "777-77-77777"],
    "대표자": ["홍길동", "김철수", "이영희", "박민수", "최유진", "정다혜", "오성민"],
    "주민번호": ["800101-1234567", "820202-2345678", "830303-3456789", "840404-4567890", "850505-5678901", "860606-6789012", "870707-7890123"],
    "사업자상태": ["계속사업자", "폐업", "폐업", "계속사업자", "폐업", "계속사업자", "계속사업자"],
    "폐업일자": ["", "2020-03-01", "2021-05-10", "", "2023-01-30", "", ""]
}

# -------------------------
# 유틸 함수
# -------------------------
@st.cache_data(show_spinner=False)
def load_df_from_file(file) -> pd.DataFrame:
    """업로드 파일로부터 DataFrame 로드 (xlsx/csv 모두 지원)"""
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
    """컬럼 공백 제거 및 문자열 정리"""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].astype(str).str.strip()
    return df

# -------------------------
# 파일 업로드 UI
# -------------------------
file = st.file_uploader("사업내역 파일 업로드 (.xlsx, .xls, .csv)", type=["xlsx", "xls", "csv"])

# -------------------------
# 데이터 로드
# -------------------------
if file:
    df = load_df_from_file(file)
else:
    st.info("업로드가 없어서 예시 데이터를 사용 중이에요. 실제 파일(사업내역.xlsx)을 올리면 그걸로 분석해요.")
    df = pd.DataFrame(SAMPLE_DATA)

df = normalize_cols(df)

# 필수 컬럼 확인
required_cols = {"상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"}
missing = [c for c in required_cols if c not in df.columns]
if missing:
    st.error(f"필수 컬럼이 없어요: {', '.join(missing)}\n\n엑셀 컬럼명을 맞춰주세요.")
    st.stop()

# 폐업일자 정리
df["폐업일자"] = df["폐업일자"].replace({"": pd.NA})
df["폐업일자(파싱)"] = pd.to_datetime(df["폐업일자"], errors="coerce")

# -------------------------
# 필터 UI
# -------------------------
st.sidebar.header("필터")
status_options = sorted(df["사업자상태"].dropna().unique().tolist())
target_status = st.sidebar.multiselect("사업자상태 선택", options=status_options, default=["폐업"])

date_filter_on = st.sidebar.checkbox("폐업일자 기간으로 추가 필터", value=False)
start_date, end_date = None, None
if date_filter_on:
    min_d = pd.to_datetime(df["폐업일자(파싱)"]).min()
    max_d = pd.to_datetime(df["폐업일자(파싱)"]).max()
    col1, col2 = st.sidebar.columns(2)
    start_date = col1.date_input("시작일", value=min_d.date() if pd.notna(min_d) else None)
    end_date = col2.date_input("종료일", value=max_d.date() if pd.notna(max_d) else None)

# -------------------------
# 필터링 로직
# -------------------------
filtered = df[df["사업자상태"].isin(target_status)]

if date_filter_on and start_date and end_date:
    mask = (filtered["폐업일자(파싱)"] >= pd.to_datetime(start_date)) & (filtered["폐업일자(파싱)"] <= pd.to_datetime(end_date))
    filtered = filtered[mask]

# -------------------------
# 결과 표시
# -------------------------
display_cols = ["상호", "사업자번호", "대표자", "주민번호", "사업자상태", "폐업일자"]
filtered_display = filtered.reindex(columns=display_cols)

col1, col2 = st.columns(2)
col1.metric("전체 행 수", len(df))
col2.metric("폐업 행 수", len(filtered_display))

st.subheader("✅ 폐업자 목록")
st.dataframe(filtered_display, use_container_width=True)

# -------------------------
# 다운로드
# -------------------------
csv_bytes = filtered_display.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "⬇️ CSV 다운로드",
    data=csv_bytes,
    file_name="전체_폐업자_현황.csv",
    mime="text/csv"
)

# -------------------------
# 안내
# -------------------------
with st.expander("안내"):
    st.write(
        "- 현재 데모에서는 주민번호를 **마스킹 없이 그대로 표시**합니다.\n"
        "- 실제 개인정보가 포함된 데이터는 마스킹 처리를 권장합니다."
    )
