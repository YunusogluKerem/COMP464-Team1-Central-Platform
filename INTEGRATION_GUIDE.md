# Team 1 - Merkezi Tedarik Zinciri (Central Supply Chain) Entegrasyon Rehberi

Bu doküman, Hastane Ekiplerinin (Clients) Merkezi Depo sistemine nasıl bağlanacağını açıklar. Sistemimiz iki ana bileşenden oluşur:
1. **SOAP Web Servisi:** Stok bildirimi ve manuel sipariş için.
2. **Azure Event Hub:** Acil ve kritik stok olaylarını asenkron olarak iletmek için.

---

## 1. SOAP Servis Bağlantısı (Docker)

Sistemi Docker üzerinde ayağa kaldırdıktan sonra aşağıdaki bilgilerle erişebilirsiniz.

* **WSDL Adresi:** `http://team1-central-platform-eqajhdbjbggkfxhf.westeurope-01.azurewebsites.net/CentralServices?wsdl` (Tarayıcıda bu adresi açıp XML görüp görmediğinizi kontrol edin).
* **Servis Endpoint:** `http://team1-central-platform-eqajhdbjbggkfxhf.westeurope-01.azurewebsites.net/CentralServices`
* **Protokol:** SOAP 1.1

### Kullanılabilir Metotlar

#### A. `StockUpdate` (Stok Bildirimi)
Hastaneler günlük stok durumlarını bu metotla bildirir. Eğer stok kritik seviyenin altındaysa sistem **otomatik sipariş** oluşturur.

* **Girdiler:**
  * `hospitalId` (String): Hastane Kodu (Örn: HASTANE-A)
  * `productCode` (String): İlaç Kodu
  * `currentStockUnits` (Int): Güncel Stok
  * `dailyConsumptionUnits` (Int): Günlük Tüketim
  * `daysOfSupply` (Float): Kaç günlük stok kaldığı
  * `timestamp` (String): Tarih Saat (ISO Format)
* **Çıktı:** `success` (Boolean), `orderTriggered` (Boolean)

#### B. `CreateOrder` (Manuel Sipariş)
Acil durumlarda manuel sipariş geçmek için kullanılır.
* **Girdiler:** `hospitalId`, `productCode`, `orderQuantity`, `priority`
* **Çıktı:** `orderId` (Sipariş Takip No)

---

## 2. Azure Event Hub Bağlantısı (Serverless)

Kritik stok durumlarını (`CRITICAL_LOW`) veya sistem alarmlarını iletmek için Azure Event Hub kullanılır. Bu yapı, okul veya şirket ağlarındaki engellere takılmamak için **WebSocket** protokolünü destekler.

* **Event Hub Name:** `inventory-low-events`
* **Connection String:** *(Güvenlik nedeniyle bu repo'da paylaşılmamıştır. Lütfen Team 1 yetkilisinden özel olarak veya grup sohbetinden isteyiniz.)*

---

## 3. Örnek Python İstemci Kodları

Diğer ekipler entegrasyon için aşağıdaki hazır kod bloklarını kullanabilir.

### A. SOAP İstemcisi (Zeep Kütüphanesi ile)
```python
from zeep import Client

wsdl = 'http://localhost:8000/CentralServices?wsdl'
client = Client(wsdl=wsdl)

try:
    # Stok Güncelleme Örneği
    response = client.service.StockUpdate({
        'hospitalId': 'HASTANE-X',
        'productCode': 'MORFINE-10MG',
        'currentStockUnits': 10,
        'dailyConsumptionUnits': 5,
        'daysOfSupply': 2.0,
        'timestamp': '2026-01-08T09:00:00'
    })
    print("Servis Cevabı:", response)
except Exception as e:
    print("Hata:", e)

###B. Azure Event Hub İstemcisi (Websocket ile)
Gereksinim: pip install azure-eventhub aiohttp

B. Azure Event Hub İstemcisi (Websocket ile)
Gereksinim: pip install azure-eventhub aiohttp

import asyncio
import json
from azure.eventhub import EventData, TransportType
from azure.eventhub.aio import EventHubProducerClient

# Team 1'den aldığınız Connection String'i buraya yapıştırın
CONNECTION_STR = "Endpoint=sb://....." 
EVENT_HUB_NAME = "inventory-low-events"

async def send_critical_event():
    # TransportType.AmqpOverWebsocket: Güvenlik duvarlarını aşmak için önemlidir!
    producer = EventHubProducerClient.from_connection_string(
        conn_str=CONNECTION_STR,
        eventhub_name=EVENT_HUB_NAME,
        transport_type=TransportType.AmqpOverWebsocket
    )
    
    async with producer:
        event_batch = await producer.create_batch()
        
        # Gönderilecek veri paketi
        event_data = {
            "hospitalId": "HASTANE-X",
            "productCode": "KRITIK-ILAC",
            "status": "CRITICAL_LEVEL",
            "timestamp": "2026-01-08T10:30:00"
        }
        
        event_batch.add(EventData(json.dumps(event_data)))
        await producer.send_batch(event_batch)
        print("Kritik olay Azure bulutuna başarıyla gönderildi!")

if __name__ == '__main__':

    asyncio.run(send_critical_event())
