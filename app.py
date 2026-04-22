import time
import random
from pymongo import MongoClient
import os
import re
import requests

# ================= CONFIG =================
MONGO_URI = os.getenv("MONGO_URI")
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

INTERVALO_MIN = 180  # 3 minutos
INTERVALO_MAX = 600  # 10 minutos

# ================= DIAGNÓSTICO MONGODB =================
print("🔍 TESTANDO CONEXÃO COM MONGODB...")

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client['shopee_bot_db']

    colls = {
        "SHOPEE": db['produtos'],
        "ML": db['produtos_ml'],
        "SHEIN": db['produtos_shein']
    }

    col_config = db['configuracoes']

    print("✅ Mongo conectado com sucesso!")

    for nome, col in colls.items():
        total = col.count_documents({})
        aprovados = col.count_documents({"status": "aprovado"})
        print(f"📊 {nome}: {total} total | {aprovados} aprovados")

except Exception as e:
    print(f"❌ ERRO MONGODB: {e}")
    raise

# ================= DESCONTO =================
def calcular_desconto(de, por):
    try:
        def limpar(v):
            if not v: return 0
            v = re.sub(r'[^\d,.]', '', str(v))
            if ',' in v:
                v = v.replace('.', '').replace(',', '.')
            return float(v)

        de = limpar(de)
        por = limpar(por)

        if de > por and de > 0:
            return int(((de - por) / de) * 100)
        return 0
    except:
        return 0

# ================= LEGENDA =================
def montar_legenda(item):
    nome = item.get('nome','')
    preco = item.get('preco','')
    preco_de = item.get('preco_de','')
    link = item.get('link','')
    loja = item.get('loja','').upper()

    pct = calcular_desconto(preco_de, preco)
    tag = f" <b>(-{pct}% OFF)</b>" if pct else ""
    linha_de = f"<s>De: {preco_de}</s>\n" if pct else ""
    aviso = "⚠️ Sujeito a alteração de preço!"

    if "SHOPEE" in loja:
        return f"✴️ <b>{nome}</b>\n{linha_de}✅ <b>Por: {preco}{tag}</b>\n🏪 Loja: #Shopee 🧡\n🔗 {link}\n{aviso}"
    elif "ML" in loja:
        return f"⚡ <b>{nome}</b>\n{linha_de}🔥 <b>POR APENAS: {preco}{tag}</b>\n🏪 Loja: #MercadoLivre 🛒\n🔗 {link}\n{aviso}"
    else:
        return f"👗 <b>{nome}</b>\n{linha_de}💎 <b>PREÇO EXCLUSIVO: {preco}{tag}</b>\n🏪 Loja: #Shein 🖤\n🔗 {link}\n{aviso}"

# ================= BUSCA INTELIGENTE =================
lista_lojas = ["SHOPEE", "ML", "SHEIN"]
vez = 0

def buscar_produto():
    global vez

    print("🔍 Buscando produto...")

    # PRIORIDADE: aprovados
    for i in range(3):
        loja = lista_lojas[vez]
        col = colls[loja]

        print(f"  Verificando {loja}...")
        
        try:
            item = col.find_one({"status": "aprovado"}, max_time_ms=3000)
            if item:
                vez = (vez + 1) % 3
                print(f"✅ Produto encontrado em {loja}: {item.get('nome', 'N/A')[:40]}")
                return item, col
            else:
                print(f"    Nenhum aprovado em {loja}")
        except Exception as e:
            print(f"  ⚠️ Erro ao buscar em {loja}: {e}")
        
        vez = (vez + 1) % 3

    # FALLBACK: concluido
    print("  Buscando produtos concluídos...")
    for loja in lista_lojas:
        col = colls[loja]
        try:
            item = col.find_one({"status": "concluido"}, max_time_ms=3000)
            if item:
                print(f"🔁 Repostando antigo de {loja}")
                return item, col
        except Exception as e:
            print(f"  ⚠️ Erro no fallback {loja}: {e}")

    print("❌ Nenhum produto encontrado")
    return None, None

# ================= ENVIO TELEGRAM =================
def enviar_telegram(mensagem, foto_url=None):
    """Envia mensagem para Telegram usando requests"""
    try:
        if foto_url:
            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            payload = {
                'chat_id': CHAT_ID,
                'photo': foto_url,
                'caption': mensagem,
                'parse_mode': 'HTML'
            }
        else:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            payload = {
                'chat_id': CHAT_ID,
                'text': mensagem,
                'parse_mode': 'HTML'
            }
        
        response = requests.post(url, json=payload, timeout=30)
        result = response.json()
        
        if result.get('ok'):
            return True
        else:
            print(f"   ⚠️ API erro: {result}")
            return False
            
    except Exception as e:
        print(f"   ❌ Erro envio: {e}")
        return False

# ================= ENVIO =================
def enviar(item, col):
    tentativas = 3
    
    for tentativa in range(1, tentativas + 1):
        try:
            print(f"📤 Tentativa {tentativa}/{tentativas}")

            legenda = montar_legenda(item)
            img = item.get("imagem", "")

            print(f"📦 Produto: {item.get('nome')}")

            # Tentar enviar com imagem
            if img:
                print(f"🖼️ Enviando com imagem...")
                sucesso = enviar_telegram(legenda, img)
                
                # Se falhar, tenta sem imagem
                if not sucesso:
                    print("   Tentando sem imagem...")
                    sucesso = enviar_telegram(legenda)
            else:
                print("✉️ Enviando sem imagem...")
                sucesso = enviar_telegram(legenda)

            if sucesso:
                col.update_one({"_id": item["_id"]}, {"$set": {"status": "concluido"}})
                print("✅ Enviado com sucesso!")
                return True
            else:
                raise Exception("Falha no envio")

        except Exception as e:
            print(f"❌ ERRO tentativa {tentativa}: {e}")
            if tentativa < tentativas:
                print("   Aguardando 5s...")
                time.sleep(5)
            else:
                print("❌ Todas as tentativas falharam!")
                return False

# ================= LOOP =================
def verificar_disparo_manual():
    """Verifica se há comando manual no MongoDB"""
    try:
        cmd = col_config.find_one({"tipo": "comando_bot"})
        if cmd and cmd.get("disparar_agora"):
            print("⚡ DISPARO MANUAL DETECTADO!")
            
            # Reseta o comando primeiro
            col_config.update_one(
                {"tipo": "comando_bot"},
                {"$set": {"disparar_agora": False}}
            )
            
            # Busca e envia produto
            item, col = buscar_produto()
            if item:
                enviar(item, col)
                return True
    except Exception as e:
        print(f"⚠️ Erro no disparo manual: {e}")
    return False

def aguardar_com_verificacao(tempo_total):
    """Aguarda mas verifica comando manual a cada 5 segundos"""
    print(f"⏱️ Aguardando {tempo_total}s (verificando comando manual a cada 5s)...")
    
    intervalo = 5  # Verifica a cada 5 segundos
    passados = 0
    
    while passados < tempo_total:
        # Verifica se há disparo manual
        if verificar_disparo_manual():
            return True  # Disparo manual foi executado
        
        # Dorme pelo intervalo ou pelo tempo restante
        dormir = min(intervalo, tempo_total - passados)
        time.sleep(dormir)
        passados += dormir
    
    return False

def loop():
    print("🔄 BOT INICIADO - LOOP RODANDO...")
    print(f"⏱️ Intervalo: {INTERVALO_MIN}s - {INTERVALO_MAX}s")

    while True:
        try:
            # Verifica disparo manual antes de buscar
            verificar_disparo_manual()
            
            item, col = buscar_produto()

            if item:
                enviar(item, col)
                tempo = random.randint(INTERVALO_MIN, INTERVALO_MAX)
                aguardar_com_verificacao(tempo)
            else:
                print("⏳ Nenhum produto, aguardando 30s...")
                aguardar_com_verificacao(30)

        except Exception as e:
            print(f"❌ ERRO NO LOOP: {e}")
            time.sleep(10)

# ================= START =================
if __name__ == "__main__":
    loop()
