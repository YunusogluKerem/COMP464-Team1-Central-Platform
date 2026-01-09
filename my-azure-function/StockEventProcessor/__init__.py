import logging
import json
import os
import datetime
import azure.functions as func
import pg8000.native
import ssl
import uuid
from typing import List

# ============================================
# Decision Engine (SOAP ile Aynı Mantık)
# ============================================
class DecisionEngine:
    THRESHOLD_CRITICAL = 2.0  # Gün cinsinden kritik eşik
    THRESHOLD_URGENT = 1.0    # Gün cinsinden acil eşik
    RESTOCK_DAYS = 7          # Hedef stok gün sayısı

    @staticmethod
    def evaluate(days_of_supply: float, daily_consumption: int, current_stock: int) -> dict:
        """
        SOAP servisi ile aynı karar verme mantığı.
        Stok seviyesine göre sipariş kararı verir.
        """
        result = {
            'should_order': False,
            'priority': None,
            'order_quantity': 0,
            'reason': ''
        }
        
        if days_of_supply < DecisionEngine.THRESHOLD_CRITICAL:
            result['should_order'] = True
            # Hedef stok = günlük tüketim * hedef gün sayısı
            target_stock = daily_consumption * DecisionEngine.RESTOCK_DAYS
            calc_quantity = target_stock - current_stock
            result['order_quantity'] = max(int(calc_quantity), daily_consumption)

            if days_of_supply < DecisionEngine.THRESHOLD_URGENT:
                result['priority'] = 'URGENT'
                result['reason'] = f'CRITICAL: {days_of_supply:.1f} days (< {DecisionEngine.THRESHOLD_URGENT})'
            else:
                result['priority'] = 'HIGH'
                result['reason'] = f'LOW STOCK: {days_of_supply:.1f} days (< {DecisionEngine.THRESHOLD_CRITICAL})'
        else:
            result['reason'] = f'Adequate stock: {days_of_supply:.1f} days'

        return result


def main(events: List[func.EventHubEvent], outputEvent: func.Out[str]):
    logging.info('>>> SERVERLESS PROCESSOR (FULL MODE) BAŞLADI <<<')
    
    # DB Bağlantısı Hazırlığı
    db_host = os.environ.get("DB_HOST")
    db_password = os.environ.get("DB_PASSWORD")
    conn = None
    
    try:
        ssl_context = ssl.create_default_context()
        conn = pg8000.native.Connection(
            user=os.environ.get("DB_USER"),
            password=db_password,
            host=db_host,
            database=os.environ.get("DB_NAME"),
            ssl_context=ssl_context
        )
    except Exception as e:
        logging.error(f"DB Bağlantı Hatası: {str(e)}")

    # Olayları İşle
    for event in events:
        start_time = datetime.datetime.now()
        try:
            body = event.get_body().decode('utf-8')
            data = json.loads(body)
            
            # Event verilerini çıkar
            event_id = data.get('eventId', f"evt-{uuid.uuid4()}")
            hospital_id = data.get("hospitalId")
            product_code = data.get("productCode")
            current_stock = int(data.get('currentStockUnits', 0))
            daily_consumption = int(data.get('dailyConsumptionUnits', 1))
            days_of_supply = float(data.get('daysOfSupply', 99))
            
            logging.info(f"📦 Event alındı: {hospital_id}/{product_code} - {days_of_supply:.1f} gün stok")
            
            # 1. StockEvents tablosuna kaydet (SOAP ile aynı)
            if conn:
                try:
                    conn.run(
                        """INSERT INTO StockEvents 
                           (event_id, hospital_id, product_code, current_stock_units, 
                            daily_consumption_units, days_of_supply, event_source, received_timestamp)
                           VALUES (:eid, :hid, :prod, :stock, :daily, :days, 'Serverless', :ts)""",
                        eid=event_id,
                        hid=hospital_id,
                        prod=product_code,
                        stock=current_stock,
                        daily=daily_consumption,
                        days=days_of_supply,
                        ts=datetime.datetime.utcnow()
                    )
                except Exception as db_err:
                    logging.warning(f"StockEvents insert hatası (tablo yok olabilir): {db_err}")

            # 2. Decision Engine ile karar ver (SOAP ile AYNI mantık)
            decision = DecisionEngine.evaluate(days_of_supply, daily_consumption, current_stock)
            logging.info(f"🧠 Karar: {decision['reason']}")
            
            if decision['should_order']:
                # 3. Sipariş ID Oluştur (SOAP formatı ile uyumlu)
                order_id = f"ORD-{datetime.datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
                
                logging.info(f"🚨 SİPARİŞ OLUŞTURULUYOR! ID: {order_id}, Miktar: {decision['order_quantity']}, Öncelik: {decision['priority']}")

                # 4. Orders tablosuna kaydet (SOAP ile aynı yapı)
                if conn:
                    try:
                        conn.run(
                            """INSERT INTO orders (
                                order_id, hospital_id, product_code, order_quantity, 
                                priority, order_status, order_source, created_at
                            ) VALUES (:oid, :hid, :prod, :qty, :prio, 'PENDING', 'Serverless', :time)""",
                            oid=order_id,
                            hid=hospital_id,
                            prod=product_code,
                            qty=decision['order_quantity'],  # Dinamik hesaplanan miktar
                            prio=decision['priority'],       # Dinamik hesaplanan öncelik
                            time=datetime.datetime.utcnow()
                        )
                        logging.info("💾 Orders kaydı başarılı.")
                    except Exception as db_err:
                        logging.error(f"Orders insert hatası: {db_err}")

                # 5. DecisionLogs tablosuna kaydet (SOAP ile aynı)
                if conn:
                    try:
                        conn.run(
                            """INSERT INTO DecisionLogs 
                               (decision_id, event_id, order_id, decision_type, decision_reason, 
                                days_of_supply_at_decision, threshold_used)
                               VALUES (:did, :eid, :oid, 'ORDER_CREATED', :reason, :days, :thresh)""",
                            did=f"dec-{uuid.uuid4()}",
                            eid=event_id,
                            oid=order_id,
                            reason=decision['reason'],
                            days=days_of_supply,
                            thresh=DecisionEngine.THRESHOLD_CRITICAL
                        )
                    except Exception as db_err:
                        logging.warning(f"DecisionLogs insert hatası: {db_err}")

                # 6. Tahmini teslimat tarihi hesapla
                estimated_delivery = (datetime.datetime.utcnow() + datetime.timedelta(days=2)).isoformat() + "Z"

                # 7. Event Hub'a OrderCreationCommand gönder (Schema uyumlu)
                command_message = {
                    "commandId": f"cmd-{uuid.uuid4()}",
                    "commandType": "CreateOrder",  # Schema: const "CreateOrder"
                    "orderId": order_id,
                    "hospitalId": hospital_id,
                    "productCode": product_code,
                    "orderQuantity": decision['order_quantity'],
                    "priority": decision['priority'],
                    "estimatedDeliveryDate": estimated_delivery,
                    "warehouseId": "CENTRAL-WAREHOUSE",
                    "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
                }
                
                outputEvent.set(json.dumps(command_message))
                logging.info(f"📤 Event Hub'a (order-commands) iletildi: {order_id}")

            else:
                # Sipariş gerekmiyorsa da logla (SOAP ile aynı)
                logging.info(f"✅ Stok yeterli, sipariş oluşturulmadı: {decision['reason']}")
                
                if conn:
                    try:
                        conn.run(
                            """INSERT INTO DecisionLogs 
                               (decision_id, event_id, decision_type, decision_reason, 
                                days_of_supply_at_decision, threshold_used)
                               VALUES (:did, :eid, 'ORDER_SKIPPED', :reason, :days, :thresh)""",
                            did=f"dec-{uuid.uuid4()}",
                            eid=event_id,
                            reason=decision['reason'],
                            days=days_of_supply,
                            thresh=DecisionEngine.THRESHOLD_CRITICAL
                        )
                    except Exception as db_err:
                        logging.warning(f"DecisionLogs (skip) insert hatası: {db_err}")

            # 8. ESBLogs tablosuna kaydet (SOAP ile aynı - latency takibi)
            if conn:
                try:
                    latency_ms = int((datetime.datetime.now() - start_time).total_seconds() * 1000)
                    conn.run(
                        """INSERT INTO ESBLogs 
                           (log_id, message_id, source_hospital_id, target_service, latency_ms, status)
                           VALUES (:lid, :mid, :hid, 'StockEventProcessor', :lat, 'SUCCESS')""",
                        lid=f"log-{uuid.uuid4()}",
                        mid=event_id,
                        hid=hospital_id,
                        lat=latency_ms
                    )
                except Exception as db_err:
                    logging.warning(f"ESBLogs insert hatası: {db_err}")

        except Exception as e:
            logging.error(f"Event işleme hatası: {str(e)}")

    if conn:
        conn.close()
    
    logging.info('>>> SERVERLESS PROCESSOR TAMAMLANDI <<<')