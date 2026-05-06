import os
import requests
import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
import database
import models
import schemas
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Painel Monitor NFE")

# Criar tabelas
models.Base.metadata.create_all(bind=database.engine)

# Montar pasta de arquivos estáticos
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_settings(db: Session):
    settings = db.query(models.SystemSettings).first()
    if not settings:
        settings = models.SystemSettings(
            evo_url=os.getenv("EVOLUTION_API_URL", ""),
            evo_token=os.getenv("EVOLUTION_APIKEY", ""),
            evo_instance=os.getenv("EVOLUTION_INSTANCE", ""),
            evo_number=os.getenv("EVOLUTION_NUMBER", ""),
            summary_interval_hours=12.0,
            last_summary_sent=datetime.now(timezone.utc)
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings

def send_whatsapp_message(text: str, db: Session):
    settings = get_settings(db)
    if not all([settings.evo_url, settings.evo_instance, settings.evo_token, settings.evo_number]):
        print("Configuração da Evolution API incompleta. Mensagem não enviada.")
        return

    endpoint = f"{settings.evo_url}/message/sendText/{settings.evo_instance}"
    headers = {
        "apikey": settings.evo_token,
        "Content-Type": "application/json"
    }
    
    payload = {
        "number": settings.evo_number,
        "options": {
            "delay": 1200,
            "presence": "composing"
        },
        "textMessage": {
            "text": text
        }
    }
    
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"Mensagem enviada com sucesso para {settings.evo_number}")
    except Exception as e:
        print(f"Falha ao enviar mensagem WhatsApp: {e}")

async def summary_worker():
    while True:
        try:
            db = database.SessionLocal()
            settings = get_settings(db)
            
            now = datetime.now(timezone.utc)
            last_sent = settings.last_summary_sent
            
            # Se last_sent não tem timezone, assume utc
            if last_sent and last_sent.tzinfo is None:
                last_sent = last_sent.replace(tzinfo=timezone.utc)
            
            if not last_sent:
                last_sent = now - timedelta(hours=settings.summary_interval_hours)
                settings.last_summary_sent = last_sent
                db.commit()

            interval_seconds = settings.summary_interval_hours * 3600
            
            if (now - last_sent).total_seconds() >= interval_seconds:
                # Gerar Resumo
                logs = db.query(models.ErrorLog).filter(models.ErrorLog.created_at >= last_sent).all()
                total_errors = len(logs)
                
                text = f"📊 *Resumo Monitor NFE ({settings.summary_interval_hours}h)* 📊\n\n"
                text += f"Nas últimas {settings.summary_interval_hours}h, tivemos:\n"
                text += f"⚠️ *{total_errors} novos erros* registrados.\n"
                
                if total_errors > 0:
                    # Encontrar a entidade com mais erros nesse periodo
                    from collections import Counter
                    entities = Counter([l.entity_name for l in logs])
                    top_entity = entities.most_common(1)[0]
                    text += f"🏢 Entidade com mais problemas: *{top_entity[0]}* ({top_entity[1]} erros)\n"
                else:
                    text += "✅ Nenhum erro ocorreu neste período!\n"
                
                send_whatsapp_message(text, db)
                
                settings.last_summary_sent = now
                db.commit()
                
            db.close()
        except Exception as e:
            print(f"Erro no summary_worker: {e}")
        
        await asyncio.sleep(60) # checa a cada 1 min

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(summary_worker())

@app.post("/api/webhook", response_model=schemas.ErrorLogResponse)
def receive_error_log(log: schemas.ErrorLogCreate, db: Session = Depends(database.get_db)):
    db_log = models.ErrorLog(**log.model_dump())
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    
    text = (
        f"🚨 *Alerta Monitor NFE* 🚨\n\n"
        f"🏢 *Entidade:* {log.entity_name}\n"
        f"⚠️ *Erro:* {log.error_category}\n"
        f"📄 *Detalhe:* {log.original_error}"
    )
    send_whatsapp_message(text, db)
    
    return db_log

@app.get("/api/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(database.get_db)):
    total_errors = db.query(models.ErrorLog).count()
    common_errors = db.query(
        models.ErrorLog.error_category, 
        func.count(models.ErrorLog.id).label('count')
    ).group_by(models.ErrorLog.error_category).order_by(func.count(models.ErrorLog.id).desc()).limit(5).all()
    
    entities = db.query(
        models.ErrorLog.entity_name, 
        func.count(models.ErrorLog.id).label('count')
    ).group_by(models.ErrorLog.entity_name).order_by(func.count(models.ErrorLog.id).desc()).limit(5).all()
    
    latest = db.query(models.ErrorLog).order_by(models.ErrorLog.created_at.desc()).limit(10).all()
    
    return {
        "total": total_errors,
        "common_errors": [{"category": c[0], "count": c[1]} for c in common_errors],
        "top_entities": [{"entity": e[0], "count": e[1]} for e in entities],
        "latest": [{"id": l.id, "entity": l.entity_name, "category": l.error_category, "date": l.created_at.isoformat()} for l in latest]
    }

@app.get("/api/settings", response_model=schemas.SystemSettingsResponse)
def api_get_settings(db: Session = Depends(database.get_db)):
    return get_settings(db)

@app.post("/api/settings", response_model=schemas.SystemSettingsResponse)
def api_update_settings(settings_data: schemas.SystemSettingsUpdate, db: Session = Depends(database.get_db)):
    settings = get_settings(db)
    settings.evo_url = settings_data.evo_url
    settings.evo_token = settings_data.evo_token
    settings.evo_instance = settings_data.evo_instance
    settings.evo_number = settings_data.evo_number
    settings.summary_interval_hours = settings_data.summary_interval_hours
    db.commit()
    db.refresh(settings)
    return settings

@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()
