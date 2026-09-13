import streamlit as st
from pymavlink import mavutil
import pandas as pd
import plotly.express as px
import tempfile
import datetime
import os
import re

# ==========================================
# ส่วนหัวโปรแกรม (Header)
# ==========================================
st.title("🚁 ระบบเปิดดูข้อมูล Log โดรนเกษตร")
st.write("By ช่างเอฟนอกบ้าน")
st.write("เวอร์ชั่น 2.0.0 (ฉบับ Log Viewer เน้นอ่านข้อมูลกราฟ, พารามิเตอร์ และข้อความระบบ)")
st.write("อัปโหลดไฟล์ .bin ของคุณที่นี่ เพื่อตรวจสอบข้อมูลการบิน")
st.write("---")

# 1. ส่วนรับอัปโหลดไฟล์
uploaded_file = st.file_uploader("ลากไฟล์ .bin มาวางตรงนี้", type=["bin", "BIN"])

if uploaded_file is not None:
    status_msg = st.empty() 
    status_msg.info("⏳ กำลังสแกนข้อมูลทั้งไฟล์... กรุณารอสักครู่")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".BIN") as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        temp_file_path = tmp_file.name

    try:
        mlog = mavutil.mavlink_connection(temp_file_path)
        
        raw_log_data = {}
        sys_msg_logs = []
        flight_params = {} 
        
        firmware_ver = "ไม่ระบุ"
        fc_model = "ไม่ระบุ"
        pixhawk_id = "ไม่ระบุ"
        flight_date = "ไม่พบข้อมูล"
        flight_time_str = "ไม่พบข้อมูล"
        
        total_flight_time = 0.0
        start_time = None

        while True:
            msg = mlog.recv_match(blocking=False)
            if not msg: break 
            
            msg_type = msg.get_type()
            
            # --- 1. ดึงพารามิเตอร์ทั้งหมด (PARM) ---
            if msg_type == 'PARM':
                p_name = getattr(msg, 'Name', getattr(msg, 'Param_Name', ''))
                p_val = getattr(msg, 'Value', getattr(msg, 'Param_Value', 0.0))
                if p_name:
                    flight_params[p_name] = p_val
                continue

            # --- 2. จัดการเวลา (TimeUS) ---
            time_sec = getattr(msg, 'TimeUS', 0) / 1e6
            if start_time is None and time_sec > 0:
                start_time = time_sec
            rel_time = round(time_sec - start_time, 2) if start_time else 0
            if rel_time > total_flight_time: total_flight_time = rel_time

            # --- 3. ดึงข้อความแจ้งเตือน (MSG) & ข้อมูลบอร์ด ---
            if msg_type == 'MSG':
                text = getattr(msg, 'Message', '').strip()
                sys_msg_logs.append({'เวลา (วินาที)': rel_time, 'ข้อความแจ้งเตือน (Message)': text})
                
                # ระบบดักจับ Firmware
                if firmware_ver == "ไม่ระบุ":
                    if re.search(r'\([a-fA-F0-9]{7,8}\)', text) or re.search(r'V\d+\.\d+', text):
                        if 'ChibiOS' not in text and 'mode' not in text.lower():
                            firmware_ver = text
                
                # ระบบดักจับ Pixhawk ID และรุ่น
                if pixhawk_id == "ไม่ระบุ":
                    match = re.match(r'^([a-zA-Z0-9\+\-\_]+)\s+([0-9A-Fa-f]{4,}(?:\s+[0-9A-Fa-f]{4,})*)$', text)
                    if match:
                        raw_model = match.group(1) 
                        pixhawk_id = text          
                        if raw_model.lower() == 'fmuv3':
                            fc_model = "Pixhawk1 หรือ PixhackV3 (fmuv3)"
                        elif raw_model.lower() == 'fmuv2':
                            fc_model = "Pixhawk1 (fmuv2)"
                        elif raw_model.lower() == 'fmuv4':
                            fc_model = "Pixracer (fmuv4)"
                        else:
                            fc_model = raw_model
                continue 

            # --- 4. ดึงเวลาทำการบินจาก GPS ---
            elif msg_type == 'GPS':
                gwk = getattr(msg, 'GWk', 0)
                ms = getattr(msg, 'GMS', 0)
                if gwk > 0 and flight_date == "ไม่พบข้อมูล":
                    try:
                        gps_epoch = datetime.datetime(1980, 1, 6)
                        utc_time = gps_epoch + datetime.timedelta(weeks=gwk, milliseconds=ms)
                        thai_time = utc_time + datetime.timedelta(hours=7)
                        flight_date = thai_time.strftime("%d/%m/%Y")
                        flight_time_str = thai_time.strftime("%H:%M:%S น.")
                    except Exception:
                        pass

            if msg_type in ['FMT', 'MULT']: 
                continue

            # --- 5. ดึงข้อมูลตัวเลขทั้งหมดเก็บไว้พล็อตกราฟอิสระ ---
            msg_dict = msg.to_dict()
            numeric_data = {'Time': rel_time}
            for k, v in msg_dict.items():
                if isinstance(v, (int, float)) and k not in ['mavpackettype', 'TimeUS']:
                    numeric_data[k] = v
            
            if len(numeric_data) > 1:
                if msg_type not in raw_log_data:
                    raw_log_data[msg_type] = []
                raw_log_data[msg_type].append(numeric_data)

        mlog.close()
        status_msg.success("✅ สแกนไฟล์ Log เสร็จสิ้น!")

        # ==========================================
        # 1. ข้อมูล Metadata
        # ==========================================
        st.subheader("ℹ️ ข้อมูลระบบและรายละเอียดการบิน")
        st.markdown(f"""
        - **Pixhawk ID :** {pixhawk_id}
        - **Flight Controller :** {fc_model}
        - **Firmware Version :** {firmware_ver}
        - **วันที่ทำการบิน :** {flight_date}
        - **เวลาการบิน :** {flight_time_str}
        - **ระยะเวลาบันทึก Log :** {total_flight_time:.1f} วินาที
        - **จำนวนพารามิเตอร์ที่พบ :** {len(flight_params)} พารามิเตอร์
        """)
        st.write("---")

        # ==========================================
        # 2. แสดงตารางข้อความแจ้งเตือน (System Messages)
        # ==========================================
        st.subheader("📝 ข้อความแจ้งเตือนจากระบบ (System Logs)")
        if len(sys_msg_logs) > 0:
            df_msgs = pd.DataFrame(sys_msg_logs)
            st.dataframe(df_msgs, use_container_width=True, hide_index=True)
        else:
            st.info("ไม่พบข้อความแจ้งเตือน (MSG) ใน Log นี้")
        st.write("---")

        # ==========================================
        # 3. ค้นหาพารามิเตอร์ (Parameter Inspector)
        # ==========================================
        with st.expander("⚙️ ตรวจสอบค่าพารามิเตอร์ทั้งหมดในกล่อง (Parameter Inspector)"):
            if len(flight_params) > 0:
                search_param = st.text_input("ค้นหาชื่อพารามิเตอร์ (เช่น BATT, MOT, ATC, EKF):", "").upper()
                df_params = pd.DataFrame(list(flight_params.items()), columns=['Parameter Name', 'Value'])
                if search_param:
                    df_params = df_params[df_params['Parameter Name'].str.contains(search_param)]
                st.dataframe(df_params, use_container_width=True, hide_index=True)
            else:
                st.write("ไม่พบตารางพารามิเตอร์ในไฟล์ Log นี้")
        st.write("---")

        # ==========================================
        # 4. เครื่องมือเลือกดูกราฟอิสระ (Custom Log Viewer)
        # ==========================================
        st.subheader("🔍 เครื่องมือดูกราฟอิสระ")
        available_msg_types = sorted(list(raw_log_data.keys()))
        
        selected_msg = st.selectbox(
            "เลือกหัวข้อข้อมูลที่ต้องการดู (เช่น RCOU, ATT, BAT, VIBE, GPS):",
            available_msg_types,
            index=None,
            placeholder="คลิกเพื่อเลือกหัวข้อ..."
        )

        if selected_msg:
            df_selected = pd.DataFrame(raw_log_data[selected_msg])
            available_fields = [c for c in df_selected.columns if c != 'Time']
            
            selected_fields = st.multiselect(
                f"เลือกพารามิเตอร์ของ {selected_msg}:",
                options=available_fields,
                default=[],
                key=f"ms_key_{selected_msg}",
                placeholder="คลิกเพื่อเลือกค่าที่ต้องการพล็อตกราฟ..."
            )

            if len(selected_fields) > 0:
                # สร้างกราฟ Plotly
                fig_custom = px.line(df_selected, x='Time', y=selected_fields, title=f"กราฟข้อมูล {selected_msg}")
                fig_custom.update_layout(hovermode="x unified", margin=dict(t=40, b=40))
                
                # ตั้งค่า Legend แบบ Mission Planner
                fig_custom.for_each_trace(lambda trace: trace.update(
                    name=f"{selected_msg}.{trace.name} | Min: {df_selected[trace.name].min():.2f}  Max: {df_selected[trace.name].max():.2f}  Mean: {df_selected[trace.name].mean():.2f}"
                ))
                fig_custom.update_layout(
                    legend=dict(
                        bordercolor="Black", 
                        borderwidth=1, 
                        bgcolor="rgba(255, 255, 255, 0.95)",
                        orientation="h", 
                        yanchor="top", 
                        y=-0.25, 
                        xanchor="center", 
                        x=0.5
                    )
                )
                st.plotly_chart(fig_custom, use_container_width=True)
            else:
                st.info(f"👈 กรุณาเลือกพารามิเตอร์ของ {selected_msg} ที่ช่องด้านบนเพื่อแสดงกราฟ")

    finally:
        # พยายามลบไฟล์ Temp ทิ้งเมื่อประมวลผลเสร็จ
        try:
            os.remove(temp_file_path)
        except Exception:
            pass