import streamlit as st
import pandas as pd
import psycopg2
import plotly.express as px
import plotly.graph_objects as go
import os
import time
from datetime import datetime

# --- VERİTABANI BAĞLANTISI ---
# Docker-compose veya Azure ayarlarınızla uyumlu olmalı
DB_HOST = "team1-postgres-db.postgres.database.azure.com"
DB_NAME = "postgres"
DB_USER = "admin1"
DB_PASS = "Root1234!"
DB_PORT = 5432

def get_db_connection():
    try:
        return psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            sslmode="require"  # <-- BU SATIR AZURE İÇİN ÇOK ÖNEMLİ
        )
    except Exception as e:
        st.error(f"Veritabanı bağlantı hatası: {e}")
        return None

# --- SAYFA AYARLARI ---
st.set_page_config(
    page_title="Team 1 - Medical Supply Chain Dashboard",
    page_icon="🏥",
    layout="wide"
)

st.title("🏥 Central Medical Supply Chain - Monitoring Dashboard")
st.markdown("**Team 1** | SOA vs Serverless Architecture Comparison")

# Otomatik yenileme butonu
if st.button('🔄 Verileri Yenile'):
    st.rerun()

conn = get_db_connection()

if conn:
    # ---------------------------------------------------------
    # 1. KPI KARTLARI (ÜST BÖLÜM)
    # ---------------------------------------------------------
    col1, col2, col3, col4 = st.columns(4)

    # Toplam Sipariş
    df_orders = pd.read_sql("SELECT COUNT(*) as count FROM Orders", conn)
    total_orders = df_orders['count'][0]
    col1.metric("Toplam Sipariş", total_orders)

    # Toplam Event
    df_events = pd.read_sql("SELECT COUNT(*) as count FROM StockEvents", conn)
    total_events = df_events['count'][0]
    col2.metric("İşlenen Stok Olayı", total_events)

    # Bekleyen Siparişler
    df_pending = pd.read_sql("SELECT COUNT(*) as count FROM Orders WHERE order_status = 'PENDING'", conn)
    pending_orders = df_pending['count'][0]
    col3.metric("Bekleyen Sipariş", pending_orders, delta_color="inverse")

    # Kritik Stok Uyarısı (Days of Supply < 2)
    df_critical = pd.read_sql("SELECT COUNT(*) as count FROM StockEvents WHERE days_of_supply < 2", conn)
    critical_alerts = df_critical['count'][0]
    col4.metric("Kritik Stok Bildirimi", critical_alerts, delta="-High Priority", delta_color="inverse")

    st.markdown("---")

    # ---------------------------------------------------------
    # 2. SOA vs SERVERLESS PERFORMANS KARŞILAŞTIRMASI (Raporda İstenen)
    # ---------------------------------------------------------
    st.subheader("🚀 Mimari Performans Karşılaştırması (SOA vs Serverless)")
    
    c1, c2 = st.columns(2)

    # Gecikme (Latency) Verilerini Çek
    # SOA için ESBLogs tablosundan, Serverless için StockEvents (processed - received) farkından
    
    # DÜZELTİLMİŞ SORGU: Her iki mimariyi de ESBLogs tablosundan çeker
    sql_latency = """
    SELECT 
        CASE 
            WHEN target_service = 'StockEventProcessor' THEN 'Serverless'
            ELSE 'SOA' 
        END as architecture, 
        AVG(latency_ms) as avg_latency
    FROM ESBLogs
    WHERE status = 'SUCCESS'
    GROUP BY 1
    HAVING AVG(latency_ms) IS NOT NULL
    """
    df_latency = pd.read_sql(sql_latency, conn)

    with c1:
        if not df_latency.empty:
            fig_lat = px.bar(
                df_latency, 
                x="architecture", 
                y="avg_latency", 
                color="architecture",
                title="Ortalama Gecikme (ms) - Düşük Olan İyidir",
                text_auto='.1f',
                color_discrete_map={'SOA': '#FFA15A', 'Serverless': '#636EFA'}
            )
            st.plotly_chart(fig_lat, use_container_width=True)
        else:
            st.info("Henüz gecikme verisi yok.")

    # İş Hacmi (Event Sayısı) Karşılaştırması
    with c2:
        df_source_dist = pd.read_sql("SELECT event_source, COUNT(*) as count FROM StockEvents GROUP BY event_source", conn)
        if not df_source_dist.empty:
            fig_pie = px.pie(
                df_source_dist, 
                values='count', 
                names='event_source', 
                title='İşlenen Olayların Mimariye Göre Dağılımı',
                hole=0.4,
                color_discrete_map={'SOA': '#FFA15A', 'Serverless': '#636EFA'}
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("Henüz olay verisi yok.")

    # ---------------------------------------------------------
    # 3. HASTANE VE SİPARİŞ ANALİZİ
    # ---------------------------------------------------------
    st.subheader("🏥 Hastane Bazlı Analizler")
    
    row2_1, row2_2 = st.columns([2, 1])

    with row2_1:
        # Hastanelere göre sipariş sayıları
        sql_hosp_orders = """
        SELECT hospital_id, priority, COUNT(*) as order_count 
        FROM Orders 
        GROUP BY hospital_id, priority
        ORDER BY order_count DESC
        """
        df_hosp_orders = pd.read_sql(sql_hosp_orders, conn)
        
        if not df_hosp_orders.empty:
            fig_bar = px.bar(
                df_hosp_orders, 
                x="hospital_id", 
                y="order_count", 
                color="priority",
                title="Hastanelere Göre Sipariş Sayısı ve Öncelik Durumu",
                barmode='group',
                color_discrete_map={'URGENT': 'red', 'HIGH': 'orange', 'NORMAL': 'green'}
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("Sipariş verisi bulunamadı.")

    with row2_2:
        # Son 10 Sipariş Tablosu
        st.markdown("##### Son Eklenen Siparişler")
        df_last_orders = pd.read_sql(
            "SELECT order_id, hospital_id, product_code, priority, created_at FROM Orders ORDER BY created_at DESC LIMIT 5", 
            conn
        )
        st.dataframe(df_last_orders, hide_index=True)

    # ---------------------------------------------------------
    # 4. GERÇEK ZAMANLI AKIŞ & SAĞLIK DURUMU
    # ---------------------------------------------------------
    st.subheader("📈 Throughput Trend (Son 24 Saat)")
    
    # Zaman serisi verisi (Saatlik gruplama)
    sql_trend = """
    SELECT date_trunc('hour', received_timestamp) as time_bucket, event_source, COUNT(*) as event_count
    FROM StockEvents
    WHERE received_timestamp > NOW() - INTERVAL '24 hours'
    GROUP BY 1, 2
    ORDER BY 1
    """
    df_trend = pd.read_sql(sql_trend, conn)
    
    if not df_trend.empty:
        fig_line = px.line(
            df_trend, 
            x="time_bucket", 
            y="event_count", 
            color="event_source",
            markers=True,
            title="Saatlik Olay Akışı (Event Throughput)",
            color_discrete_map={'SOA': '#FFA15A', 'Serverless': '#636EFA'}
        )
        st.plotly_chart(fig_line, use_container_width=True)
    else:
        st.info("Son 24 saatte veri akışı yok.")

    conn.close()

else:
    st.error("Veritabanına bağlanılamadı. Lütfen DB ayarlarını kontrol edin.")