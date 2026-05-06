import os
import time
import configparser
import requests
import fdb
import logging
import sys

# Configuração de Logs Nativos do Python
logger = logging.getLogger("AgenteNFSe")
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Log normal (INFO, DEBUG)
info_handler = logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "agente.log"), encoding="utf-8")
info_handler.setLevel(logging.INFO)
info_handler.setFormatter(formatter)
logger.addHandler(info_handler)

# Log de erro (ERROR, CRITICAL)
error_handler = logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "agente_error.log"), encoding="utf-8")
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(formatter)
logger.addHandler(error_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Garantir que o last_id seja salvo na pasta real do executavel
LAST_ID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_id")

def get_known_error_category(error_message):
    known_errors = {
        "RegimeEspecialTributacaoNacional": "Falta Regime Especial",
        "NullPointerException": "NullPointerException",
        "Atividade de evento sem ID": "Atividade sem ID/Endereço",
        "Erro de validação": "Erro de Validação",
        "ConstraintViolation": "Erro de Validação",
        "Erro de preenchimento": "Erro de Preenchimento",
        "api de serviços": "API de Serviços",
        "Erro ao processar a nota": "Erro Processamento",
        "Atividade não encontrada": "Atividade Não Encontrada",
        "Connection refused": "Erro de Conexão",
        "Timeout": "Tempo Excedido"
    }
    
    if not error_message:
        return "Erro Desconhecido"
        
    for key, category in known_errors.items():
        if key.lower() in error_message.lower():
            return category
            
    return "Erro Desconhecido"

def get_last_id():
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except ValueError:
                return 0
    return 0

def set_last_id(last_id):
    with open(LAST_ID_FILE, "w") as f:
        f.write(str(last_id))

def main():
    logger.info("Iniciando Agente Monitor de Notas Fiscais com Anti-Spam...")
    
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
    config = configparser.ConfigParser()
    
    if not os.path.exists(config_path):
        config['DATABASE'] = {
            'Host': 'localhost',
            'Port': '3050',
            'Database': r'C:\Fiorilli\BANCOS\SGB_DADOS\SIADADOS.FDB',
            'User': 'fscsia',
            'Password': 'csfais'
        }
        config['AGENT'] = {
            'EntityName': 'Prefeitura Exemplo',
            'PanelUrl': 'http://localhost:8000/api/webhook',
            'CheckIntervalMinutes': '5',
            'JbossUrl': 'http://localhost:8080/servicosweb-ws/rest'
        }
        with open(config_path, 'w') as configfile:
            config.write(configfile)
        logger.warning("Arquivo config.ini gerado. Ajuste os valores e reinicie.")

    config.read(config_path)
    db_host = config['DATABASE'].get('Host', 'localhost')
    db_port = config['DATABASE'].getint('Port', 3050)
    db_path = config['DATABASE'].get('Database', r'C:\Fiorilli\BANCOS\SGB_DADOS\SIADADOS.FDB')
    db_user = config['DATABASE'].get('User', 'fscsia')
    db_pass = config['DATABASE'].get('Password', 'csfais')
    
    entity_name = config['AGENT'].get('EntityName', 'Desconhecido')
    panel_url = config['AGENT'].get('PanelUrl', 'http://localhost:8000/api/webhook')
    interval_minutes = config['AGENT'].getint('CheckIntervalMinutes', 5)
    jboss_url = config['AGENT'].get('JbossUrl', 'http://localhost:8080/servicosweb-ws/rest')

    last_id = get_last_id()
    
    # Máquinas de Estado (Anti-Spam)
    db_was_offline = False
    jboss_was_offline = False

    while True:
        logger.info("Checando novos erros no banco de dados...")
        
        try:
            con = fdb.connect(
                host=db_host,
                port=db_port,
                database=db_path,
                user=db_user,
                password=db_pass,
                charset='WIN1252'
            )
            cur = con.cursor()
            
            # Se o banco estava offline e conectou agora, envia mensagem de recuperação
            if db_was_offline:
                db_was_offline = False
                try:
                    requests.post(panel_url, json={
                        "entity_name": entity_name,
                        "error_category": "Banco de Dados Restaurado",
                        "original_error": "A conexão com o banco de dados Firebird foi restabelecida com sucesso!"
                    }, timeout=10)
                    logger.info("Enviado aviso de restauração do banco.")
                except:
                    pass
            
            cur.execute(f"SELECT COD_NLE, DESCRICAO_NLE, MENSAGEM_NLE FROM NFE_LOG_ERROS WHERE COD_NLE > {last_id} ORDER BY COD_NLE ASC")
            rows = cur.fetchall()
            
            highest_id = last_id
            
            for row in rows:
                row_id = row[0]
                error_desc = f"{row[1] or ''} - {row[2] or ''}".strip(" -")
                if not error_desc:
                    error_desc = "Erro sem descrição"
                
                category = get_known_error_category(error_desc)
                if category == "Erro Desconhecido":
                    category = f"Outros: {error_desc[:50]}"
                
                payload = {
                    "entity_name": entity_name,
                    "error_category": category,
                    "original_error": error_desc
                }
                
                try:
                    resp = requests.post(panel_url, json=payload, timeout=10)
                    if resp.status_code == 200:
                        logger.info(f"Erro {row_id} enviado com sucesso para o painel.")
                    else:
                        logger.error(f"Falha ao enviar erro {row_id} - HTTP {resp.status_code}")
                except Exception as e:
                    logger.error(f"Erro de conexão com o painel ao enviar erro {row_id}: {e}")
                
                highest_id = max(highest_id, row_id)
                
            set_last_id(highest_id)
            last_id = highest_id
            
            cur.close()
            con.close()
            logger.info("Checagem de banco finalizada.")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Erro ao acessar banco de dados Firebird: {error_msg}")
            
            # Anti-Spam: Só avisa se não estava offline antes
            if not db_was_offline:
                db_was_offline = True
                payload = {
                    "entity_name": entity_name,
                    "error_category": "Banco de Dados Inacessível",
                    "original_error": f"Falha na conexão com o banco ({db_host}:{db_port}). O sistema tentará reconectar a cada {interval_minutes}min. Detalhe: {error_msg}"
                }
                try:
                    resp = requests.post(panel_url, json=payload, timeout=10)
                    if resp.status_code == 200:
                        logger.info("Alerta de banco de dados offline enviado.")
                except Exception as net_e:
                    logger.error(f"Falha ao avisar o painel sobre banco: {net_e}")

        # --- CHECAGEM JBOSS COM ANTI-SPAM ---
        if jboss_url and jboss_url.strip() != "":
            logger.info(f"Checando JBoss em {jboss_url} ...")
            try:
                jboss_resp = requests.get(jboss_url, timeout=10)
                if jboss_resp.status_code >= 500:
                    raise Exception(f"Servidor retornou código {jboss_resp.status_code}")
                
                # JBoss está vivo
                logger.info("JBoss está online e respondendo.")
                
                # Se estava offline e voltou
                if jboss_was_offline:
                    jboss_was_offline = False
                    try:
                        requests.post(panel_url, json={
                            "entity_name": entity_name,
                            "error_category": "JBoss Restaurado",
                            "original_error": "O serviço do JBoss voltou a responder com sucesso!"
                        }, timeout=10)
                        logger.info("Enviado aviso de restauração do JBoss.")
                    except:
                        pass

            except Exception as jboss_e:
                logger.error(f"Falha ao conectar no JBoss: {jboss_e}")
                
                # Só notifica se não estava offline antes
                if not jboss_was_offline:
                    jboss_was_offline = True
                    payload_jboss = {
                        "entity_name": entity_name,
                        "error_category": "JBoss Inacessível",
                        "original_error": f"O serviço JBoss parou de responder. O monitor tentará reconectar a cada {interval_minutes}min. Detalhe: {str(jboss_e)[:100]}"
                    }
                    try:
                        requests.post(panel_url, json=payload_jboss, timeout=10)
                        logger.info("Alerta de JBoss offline enviado ao painel.")
                    except Exception as net_e:
                        logger.error("Falha ao enviar alerta de JBoss ao painel.")
            
        logger.info(f"Aguardando {interval_minutes} minutos para próxima checagem...")
        time.sleep(interval_minutes * 60)

if __name__ == "__main__":
    main()
