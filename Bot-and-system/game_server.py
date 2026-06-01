"""
Servidor do Jogo de Cartas — Flask + SocketIO
Lê cartas.json do bot Necromante (somente leitura).
Estado da partida fica em memória.
"""
 
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from tinydb import TinyDB, Query
import random
import uuid
import os
import json
import copy
import threading
 
app = Flask(__name__)
app.config["SECRET_KEY"] = "necromante-jogo-secreto"
socketio = SocketIO(app, cors_allowed_origins="*")
 
CARTAS_DB_PATH = os.path.join(os.path.dirname(__file__), "cartas.json")
IMAGENS_PATH   = "/imagens"
 
salas   = {}
lobbies = {}
 
db_lock = threading.Lock()
 
VIDA_INICIAL      = 1000   # alterado de 1500 para 1000
MAX_MAO           = 6
MAX_INVOCACOES    = 2   # invocações por turno
 
def ler_usuario(discord_id: int) -> dict | None:
    with db_lock:
        db  = TinyDB(CARTAS_DB_PATH, encoding="utf-8")
        U   = Query()
        doc = db.table("usuarios").get(U.discord_id == discord_id)
        db.close()
    return doc
 
def ler_catalogo() -> dict:
    with db_lock:
        db    = TinyDB(CARTAS_DB_PATH, encoding="utf-8")
        todas = db.table("catalogo").all()
        db.close()
    return {c["carta_id"]: c for c in todas}
 
def montar_deck_jogador(discord_id: int, catalogo: dict) -> list[dict]:
    doc = ler_usuario(discord_id)
    if not doc:
        return []
    deck = []
    for entry in doc.get("bolso", []):
        cid   = entry["carta_id"]
        dados = catalogo.get(cid)
        if not dados:
            continue
        for _ in range(entry["quantidade"]):
            deck.append(copy.deepcopy(dados))
    random.shuffle(deck)
    return deck
 
POSICOES_CAMPO = 4
 
def estado_inicial(sala_id: str, j1: dict, j2: dict, catalogo: dict) -> dict:
    def jogador_base(info):
        deck = montar_deck_jogador(info["discord_id"], catalogo)
        mao  = deck[:5]
        deck = deck[5:]
        return {
            "discord_id": info["discord_id"],
            "nome":        info["nome"],
            "sid":         info["sid"],
            "vida":        VIDA_INICIAL,
            "deck":        deck,
            "mao":         mao,
            "campo_monstro":  [None] * POSICOES_CAMPO,
            "campo_efeito":   [None] * POSICOES_CAMPO,
            "cemiterio":   [],
            "deck_reiniciado": False,
            "ja_atacou":   [],
            "invocacoes":  0,
            "ativou_efeito": False,
        }
 
    moeda = random.choice([0, 1])
    return {
        "sala_id":        sala_id,
        "fase":           "sorteio",
        "turno":          moeda,
        "numero_turno":   1,
        "subfase":        "compra",
        "jogadores":      [jogador_base(j1), jogador_base(j2)],
        "pendente":       None,
        "log":            [],
        "vencedor":       None,
    }
 
def outro(idx): return 1 - idx
 
def idx_jogador(estado, sid):
    for i, j in enumerate(estado["jogadores"]):
        if j["sid"] == sid:
            return i
    return None
 
def add_log(estado, msg):
    estado["log"].append(msg)
 
def emitir_estado(sala_id):
    estado = salas.get(sala_id)
    if not estado:
        return
    for i, j in enumerate(estado["jogadores"]):
        visao = json.loads(json.dumps(estado))
        op = visao["jogadores"][outro(i)]
        op["mao_count"] = len(op["mao"])
        op["mao"] = []
        for slot in op["campo_efeito"]:
            if slot and not slot.get("revelada"):
                slot["nome"]   = "???"
                slot["imagem"] = None
                slot["efeito"] = None
                slot["gatilho"] = None
        visao["meu_indice"] = i
        socketio.emit("estado", visao, room=j["sid"])
 
def comprar_carta(jog):
    if not jog["deck"]:
        if jog["deck_reiniciado"]:
            return f"{jog['nome']} ficou sem deck pela segunda vez — DERROTA!"
        jog["deck"] = jog["cemiterio"][:]
        jog["cemiterio"] = []
        random.shuffle(jog["deck"])
        jog["deck_reiniciado"] = True
        if not jog["deck"]:
            return f"{jog['nome']} ficou sem deck — DERROTA!"
    carta = jog["deck"].pop(0)
    jog["mao"].append(carta)
    return None
 
def verificar_derrota(estado):
    for i, j in enumerate(estado["jogadores"]):
        if j["vida"] <= 0:
            return i
        if not j["deck"] and j["deck_reiniciado"]:
            return i
    return None
 
def aplicar_dano(estado, alvo_idx, dano):
    estado["jogadores"][alvo_idx]["vida"] -= dano
    if estado["jogadores"][alvo_idx]["vida"] < 0:
        estado["jogadores"][alvo_idx]["vida"] = 0
 
def aplicar_efeito_invocacao(estado, dono_idx, carta):
    op_idx  = outro(dono_idx)
    dono    = estado["jogadores"][dono_idx]
    op      = estado["jogadores"][op_idx]
    nome    = carta.get("nome", "?")
    carta_id = carta.get("carta_id", "")
    msgs = []
 
    if carta_id == "ad4bb7f2":
        aplicar_dano(estado, op_idx, 20)
        msgs.append(f"⚡ {nome}: 20 de dano direto a {op['nome']}!")
    elif carta_id == "64838808":
        count = 0
        for slot in dono["campo_monstro"]:
            if slot and slot.get("estrelas", 0) <= 2:
                slot["ataque_bonus"] = slot.get("ataque_bonus", 0) + 10
                count += 1
        if count:
            msgs.append(f"⚡ {nome}: +10 ataque para {count} monstro(s) de nível 1-2 seu(s)!")
    elif carta_id == "ad9ca8d8":
        for i, slot in enumerate(op["campo_efeito"]):
            if slot:
                op["cemiterio"].append(slot)
                op["campo_efeito"][i] = None
                msgs.append(f"⚡ {nome}: destruiu {slot['nome']} do campo de {op['nome']}!")
                break
    elif carta_id == "fd417928":
        for i, slot in enumerate(op["campo_monstro"]):
            if slot and slot.get("defesa", 999) <= 60:
                op["cemiterio"].append(slot)
                op["campo_monstro"][i] = None
                msgs.append(f"⚡ {nome}: destruiu {slot['nome']} (def≤60) de {op['nome']}!")
                break
    elif carta_id == "90d9f589":
        tipos_mortos = {"monstro", "monstro_efeito"}
        count = 0
        for slot in dono["campo_monstro"]:
            if slot and slot.get("tipo") in tipos_mortos:
                slot["ataque_bonus"] = slot.get("ataque_bonus", 0) + 15
                slot["defesa_bonus"] = slot.get("defesa_bonus", 0) + 15
                count += 1
        if count:
            msgs.append(f"⚡ {nome}: +15 atk/def para {count} morto(s)-vivo(s) seu(s)!")
    elif carta_id == "2b1df7c5":
        aplicar_dano(estado, op_idx, 30)
        msgs.append(f"⚡ {nome}: 30 de dano direto a {op['nome']}!")
    elif carta_id == "9aa49f58":
        menor_idx = None
        menor_atk = 9999
        for i, slot in enumerate(op["campo_monstro"]):
            if slot:
                atk = slot.get("ataque", 0) + slot.get("ataque_bonus", 0)
                if atk < menor_atk:
                    menor_atk = atk
                    menor_idx = i
        if menor_idx is not None:
            destruido = op["campo_monstro"][menor_idx]
            op["cemiterio"].append(destruido)
            op["campo_monstro"][menor_idx] = None
            msgs.append(f"⚡ {nome}: destruiu {destruido['nome']} (menor atk) de {op['nome']}!")
    elif carta_id == "5659eaad":
        estado["pendente"] = {"tipo": "lich_supremo", "dono_idx": dono_idx}
        msgs.append(f"⚡ {nome}: escolha uma carta no campo do oponente para destruir.")
 
    return msgs
 
def aplicar_carta_efeito(estado, dono_idx, carta, alvo=None):
    op_idx = outro(dono_idx)
    dono   = estado["jogadores"][dono_idx]
    op     = estado["jogadores"][op_idx]
    nome   = carta.get("nome", "?")
    cid    = carta.get("carta_id", "")
    msgs   = []
 
    if cid == "cf2ce29f":
        for _ in range(2):
            r = comprar_carta(dono)
            if r: msgs.append(r)
        msgs.append(f"📜 {nome}: comprou 2 cartas.")
    elif cid == "ffe91320":
        aplicar_dano(estado, op_idx, 40)
        msgs.append(f"📜 {nome}: 40 de dano direto a {op['nome']}!")
    elif cid == "f4bd3d1b":
        for i, slot in enumerate(op["campo_monstro"]):
            if slot and slot.get("ataque", 0) + slot.get("ataque_bonus", 0) <= 50:
                op["cemiterio"].append(slot)
                op["campo_monstro"][i] = None
                msgs.append(f"📜 {nome}: destruiu {slot['nome']} (atk≤50)!")
                break
    elif cid == "fb09380b":
        for i, slot in enumerate(op["campo_monstro"]):
            if slot and slot.get("defesa", 0) + slot.get("defesa_bonus", 0) <= 70:
                op["cemiterio"].append(slot)
                op["campo_monstro"][i] = None
                msgs.append(f"📜 {nome}: destruiu {slot['nome']} (def≤70)!")
                break
    elif cid == "3ea9af81":
        count = 0
        for slot in op["campo_monstro"]:
            if slot:
                slot["ataque_bonus"] = slot.get("ataque_bonus", 0) - 20
                count += 1
        msgs.append(f"📜 {nome}: -20 atk para {count} monstro(s) de {op['nome']}!")
    elif cid == "732143f8":
        if alvo is not None and dono["campo_monstro"][alvo]:
            slot = dono["campo_monstro"][alvo]
            slot["ataque_bonus"] = slot.get("ataque_bonus", 0) + 25
            slot["defesa_bonus"] = slot.get("defesa_bonus", 0) + 25
            msgs.append(f"📜 {nome}: +25 atk/def em {slot['nome']}!")
    elif cid == "9d697ada":
        if alvo is not None and op["campo_efeito"][alvo]:
            destruido = op["campo_efeito"][alvo]
            op["cemiterio"].append(destruido)
            op["campo_efeito"][alvo] = None
            msgs.append(f"📜 {nome}: destruiu {destruido['nome']} de {op['nome']}!")
        else:
            for i, slot in enumerate(op["campo_efeito"]):
                if slot:
                    op["cemiterio"].append(slot)
                    op["campo_efeito"][i] = None
                    msgs.append(f"📜 {nome}: destruiu {slot['nome']} de {op['nome']}!")
                    break
    elif cid == "b1c26eb1":
        r = comprar_carta(dono)
        if r: msgs.append(r)
        if alvo is not None and dono["campo_monstro"][alvo]:
            slot = dono["campo_monstro"][alvo]
            slot["ataque_bonus"] = slot.get("ataque_bonus", 0) + 15
            msgs.append(f"📜 {nome}: comprou 1 carta e +15 atk em {slot['nome']}!")
        else:
            msgs.append(f"📜 {nome}: comprou 1 carta.")
    elif cid == "6f3a5f32":
        if alvo is not None and dono["campo_monstro"][alvo]:
            slot = dono["campo_monstro"][alvo]
            slot["defesa_bonus"] = slot.get("defesa_bonus", 0) + 40
            msgs.append(f"📜 {nome}: +40 def em {slot['nome']}!")
    elif cid == "2340fcb7":
        for i, slot in enumerate(op["campo_monstro"]):
            if slot and slot.get("ataque", 0) + slot.get("ataque_bonus", 0) <= 80:
                op["cemiterio"].append(slot)
                op["campo_monstro"][i] = None
                msgs.append(f"📜 {nome}: destruiu {slot['nome']} (atk≤80)!")
                break
 
    return msgs
 
def verificar_armadilha(estado, evento, dono_idx_evento, dados_evento=None):
    """
    Verifica se o oponente tem uma armadilha com gatilho correspondente ao evento.
    Se sim, registra em estado["pendente"] e emite o evento ao dono da armadilha.
    Retorna True se pausou o jogo aguardando resposta, False caso contrário.
    """
    op_idx = outro(dono_idx_evento)
    op     = estado["jogadores"][op_idx]
 
    gatilhos = {
        "ataque_declarado": ["1484dc74", "cd6e3a9b"],
        "monstro_invocado": ["03c7624c"],
        "efeito_ativado":   ["b198ef62"],
        "ataque_direto":    ["0c1edc5e"],
        "monstro_destruido_combate": ["b8c4e5a5"],
    }
 
    alvo_cids = gatilhos.get(evento, [])
    for i, slot in enumerate(op["campo_efeito"]):
        if slot and slot.get("carta_id") in alvo_cids:
            estado["pendente"] = {
                "tipo":               "armadilha",
                "armadilha_idx":      i,
                "armadilha_cid":      slot["carta_id"],
                "dono_armadilha_idx": op_idx,
                "evento":             evento,
                "dados":              dados_evento,
                # guarda índices do atacante/alvo para retomar o combate se necessário
                "atacante_dono_idx":  dono_idx_evento,
                "at_idx":             (dados_evento or {}).get("monstro_idx"),
                "alvo_idx":           (dados_evento or {}).get("alvo_idx"),
            }
            add_log(estado, f"🔔 {op['nome']} pode ativar uma armadilha! ({slot['nome']})")
            emitir_estado(estado["sala_id"])
            socketio.emit("ativar_armadilha", {
                "slot_idx": i,
                "carta":    slot,
                "evento":   evento,
            }, room=op["sid"])
            return True
    return False
 
def resolver_armadilha(estado, ativar: bool):
    pend = estado["pendente"]
    estado["pendente"] = None
 
    if not ativar:
        add_log(estado, "🔕 Armadilha não ativada.")
        evento   = pend["evento"]
        at_idx   = pend.get("at_idx")
        alvo_idx = pend.get("alvo_idx")
        dono_idx = pend.get("atacante_dono_idx")
 
        if evento == "ataque_declarado":
            if at_idx is not None and alvo_idx is not None:
                if alvo_idx == -1:
                    # ataque direto: aplicar dano agora
                    atacante = estado["jogadores"][dono_idx]["campo_monstro"][at_idx]
                    if atacante:
                        atk_val = atacante.get("ataque", 0) + atacante.get("ataque_bonus", 0)
                        aplicar_dano(estado, outro(dono_idx), atk_val)
                        add_log(estado, f"⚔️ {atacante['nome']} ({atk_val}) atacou diretamente!")
                        venc = verificar_derrota(estado)
                        if venc is not None:
                            declarar_vencedor(estado, outro(venc))
                            return
                else:
                    resolver_combate(estado, dono_idx, at_idx, alvo_idx)
 
        elif evento == "ataque_direto":
            # Armadilha não ativada: aplica o dano direto normalmente
            if at_idx is not None:
                atacante_m = estado["jogadores"][dono_idx]["campo_monstro"][at_idx]
                if atacante_m:
                    atk_val = atacante_m.get("ataque", 0) + atacante_m.get("ataque_bonus", 0)
                    aplicar_dano(estado, outro(dono_idx), atk_val)
                    add_log(estado, f"⚔️ {atacante_m['nome']} atacou diretamente! {atk_val} de dano.")
                    venc = verificar_derrota(estado)
                    if venc is not None:
                        declarar_vencedor(estado, outro(venc))
                        return
 
        continuar_apos_pendente(estado)
        return
 
    # --- Ativar armadilha ---
    op_idx  = pend["dono_armadilha_idx"]
    at_idx  = pend["armadilha_idx"]
    cid     = pend["armadilha_cid"]
    evento  = pend["evento"]
    dados   = pend.get("dados") or {}
 
    op   = estado["jogadores"][op_idx]
    slot = op["campo_efeito"][at_idx]
    if not slot:
        continuar_apos_pendente(estado)
        return
 
    op["cemiterio"].append(slot)
    op["campo_efeito"][at_idx] = None
 
    atacante_idx = outro(op_idx)
    atacante     = estado["jogadores"][atacante_idx]
 
    if cid == "1484dc74":
        # Correntes Espectrais: cancela o ataque (ataque_declarado)
        m_idx = pend.get("at_idx")
        add_log(estado, f"🔒 Correntes Espectrais: ataque cancelado!")
        # remove da lista ja_atacou se tiver sido marcado prematuramente
        if m_idx is not None and atacante["campo_monstro"][m_idx]:
            cid_atacante = atacante["campo_monstro"][m_idx]["carta_id"]
            bloq = cid_atacante + "_bloqueado"
            if cid_atacante in atacante["ja_atacou"]:
                atacante["ja_atacou"].remove(cid_atacante)
            if bloq in atacante["ja_atacou"]:
                atacante["ja_atacou"].remove(bloq)
        continuar_apos_pendente(estado)
        return
 
    elif cid == "cd6e3a9b":
        # Explosão de Ossos: destrói o monstro atacante
        m_idx = pend.get("at_idx")
        if m_idx is not None and atacante["campo_monstro"][m_idx]:
            m = atacante["campo_monstro"][m_idx]
            atacante["cemiterio"].append(m)
            atacante["campo_monstro"][m_idx] = None
            add_log(estado, f"💀 Explosão de Ossos: {m['nome']} destruído!")
        continuar_apos_pendente(estado)
        return
 
    elif cid == "03c7624c":
        # Maldição do Túmulo: -30 atk/def ao monstro recém-invocado
        m_idx = dados.get("monstro_idx")
        if m_idx is not None and atacante["campo_monstro"][m_idx]:
            m = atacante["campo_monstro"][m_idx]
            m["ataque_bonus"] = m.get("ataque_bonus", 0) - 30
            m["defesa_bonus"] = m.get("defesa_bonus", 0) - 30
            add_log(estado, f"🪦 Maldição do Túmulo: {m['nome']} perde 30 atk/def!")
 
    elif cid == "b198ef62":
        add_log(estado, f"👻 Grito da Banshee: efeito cancelado!")
 
    elif cid == "0c1edc5e":
        # Neblina Sombria: ataque direto recebe metade do dano.
        # verificar_armadilha é chamado ANTES de aplicar_dano, então o dano ainda não foi aplicado.
        dano_original = dados.get("dano", 0)
        dano = dano_original // 2
        aplicar_dano(estado, op_idx, dano)
        add_log(estado, f"🌫️ Neblina Sombria: dano reduzido de {dano_original} para {dano}!")
 
    elif cid == "b8c4e5a5":
        # Contra-Ataque Espectral: aplica metade do ataque do monstro destruído ao atacante
        atk = dados.get("ataque_monstro", 0)
        dano = atk // 2
        aplicar_dano(estado, atacante_idx, dano)
        add_log(estado, f"⚔️ Contra-Ataque Espectral: {dano} de dano a {atacante['nome']}!")
 
    # Após aplicar efeito da armadilha, retomar combate ou aplicar dano direto
    if evento == "ataque_declarado":
        a_idx   = pend.get("at_idx")
        alv_idx = pend.get("alvo_idx")
        d_idx   = pend.get("atacante_dono_idx")
        if a_idx is not None and alv_idx is not None:
            if alv_idx == -1:
                # Ataque direto: Neblina Sombria já aplicou dano reduzido acima; nada mais a fazer.
                pass
            elif estado["jogadores"][d_idx]["campo_monstro"][a_idx]:
                # verifica se o monstro atacante ainda existe (pode ter sido destruído pela armadilha)
                resolver_combate(estado, d_idx, a_idx, alv_idx)
                return
    elif evento == "ataque_direto":
        # Armadilha ativada com gatilho ataque_direto (ex: futura carta).
        # Neblina Sombria (0c1edc5e) já aplicou o dano reduzido acima.
        # Qualquer outra armadilha desse gatilho deve aplicar o dano normal após o efeito.
        if cid != "0c1edc5e":
            a_idx = pend.get("at_idx")
            d_idx = pend.get("atacante_dono_idx")
            if a_idx is not None:
                atacante_m = estado["jogadores"][d_idx]["campo_monstro"][a_idx]
                if atacante_m:
                    atk_val = atacante_m.get("ataque", 0) + atacante_m.get("ataque_bonus", 0)
                    aplicar_dano(estado, op_idx, atk_val)
                    add_log(estado, f"⚔️ {atacante_m['nome']} atacou diretamente! {atk_val} de dano.")
                    venc = verificar_derrota(estado)
                    if venc is not None:
                        declarar_vencedor(estado, outro(venc))
                        return
 
    continuar_apos_pendente(estado)
 
def continuar_apos_pendente(estado):
    emitir_estado(estado["sala_id"])
    venc = verificar_derrota(estado)
    if venc is not None:
        declarar_vencedor(estado, outro(venc))
 
def declarar_vencedor(estado, venc_idx):
    estado["vencedor"] = venc_idx
    nome = estado["jogadores"][venc_idx]["nome"]
    add_log(estado, f"🏆 {nome} venceu a partida!")
    socketio.emit("fim_de_jogo", {"vencedor": nome, "log": estado["log"]},
                  room=estado["sala_id"])
 
# ── Rotas HTTP ─────────────────────────────────────────────────────────────────
 
@app.route("/")
def index():
    return render_template("game.html")
 
@app.route("/api/catalogo")
def api_catalogo():
    catalogo = ler_catalogo()
    return jsonify(catalogo)
 
from flask import send_from_directory
 
PASTA_IMAGENS = os.path.join(os.path.dirname(__file__), "imagens")
 
@app.route("/imagens/<path:nome>")
def servir_imagem(nome):
    return send_from_directory(PASTA_IMAGENS, nome)
 
# ── Eventos SocketIO ───────────────────────────────────────────────────────────
 
@socketio.on("connect")
def on_connect():
    pass
 
@socketio.on("entrar_sala")
def on_entrar_sala(data):
    sala_id    = data.get("sala_id", "").strip()
    discord_id = int(str(data.get("discord_id", 0)))
    nome       = data.get("nome", "Jogador").strip()
    sid        = request.sid
 
    if not sala_id or not discord_id:
        emit("erro", {"msg": "sala_id e discord_id são obrigatórios."})
        return
 
    join_room(sala_id)
 
    if sala_id not in lobbies:
        lobbies[sala_id] = {}
 
    lobby = lobbies[sala_id]
 
    for chave in ("j1", "j2"):
        if lobby.get(chave, {}).get("discord_id") == discord_id:
            lobby[chave]["sid"] = sid
            emit("aguardando", {"msg": "Reconectado. Aguardando oponente..." if len(lobby) < 2 else "Pronto!"})
            if sala_id in salas:
                salas[sala_id]["jogadores"][[j["discord_id"] for j in salas[sala_id]["jogadores"]].index(discord_id)]["sid"] = sid
                emitir_estado(sala_id)
            return
 
    if "j1" not in lobby:
        lobby["j1"] = {"discord_id": discord_id, "nome": nome, "sid": sid}
        emit("aguardando", {"msg": f"Sala {sala_id} criada. Aguardando oponente..."})
    elif "j2" not in lobby:
        lobby["j2"] = {"discord_id": discord_id, "nome": nome, "sid": sid}
        catalogo = ler_catalogo()
        estado   = estado_inicial(sala_id, lobby["j1"], lobby["j2"], catalogo)
        salas[sala_id] = estado
 
        j_atual = estado["jogadores"][estado["turno"]]
        add_log(estado, f"🎲 Sorteio: {j_atual['nome']} começa!")
        estado["fase"] = "turno"
        estado["subfase"] = "principal1"
        add_log(estado, f"▶ Turno 1 — {j_atual['nome']} — Fase Principal 1")
        add_log(estado, f"⚠️ Regra: primeiro jogador não pode atacar no turno 1.")
 
        emitir_estado(sala_id)
    else:
        emit("erro", {"msg": "Sala cheia."})
 
@socketio.on("invocar_monstro")
def on_invocar_monstro(data):
    sala_id   = data["sala_id"]
    estado    = salas.get(sala_id)
    if not estado or estado["vencedor"] is not None:
        return
 
    dono_idx  = idx_jogador(estado, request.sid)
    if dono_idx != estado["turno"]:
        emit("erro", {"msg": "Não é seu turno."})
        return
    if estado["subfase"] not in ("principal1", "principal2"):
        emit("erro", {"msg": "Só pode invocar na fase principal."})
        return
 
    dono = estado["jogadores"][dono_idx]
 
    if dono["invocacoes"] >= MAX_INVOCACOES:
        emit("erro", {"msg": f"Você já invocou {MAX_INVOCACOES} monstros neste turno."})
        return
 
    mao_idx   = data["mao_idx"]
    campo_idx = data["campo_idx"]
    sacrs     = data.get("sacrificios", [])
    posicao   = data.get("posicao", "ataque")
 
    if mao_idx >= len(dono["mao"]):
        emit("erro", {"msg": "Índice de mão inválido."})
        return
 
    carta = dono["mao"][mao_idx]
    if carta.get("tipo") not in ("monstro", "monstro_efeito"):
        emit("erro", {"msg": "Essa carta não é um monstro."})
        return
 
    nivel = carta.get("estrelas", 1)
 
    for i in sacrs:
        slot_sacr = dono["campo_monstro"][i]
        if slot_sacr and slot_sacr.get("recem_invocado"):
            emit("erro", {"msg": f"{slot_sacr['nome']} foi invocado neste turno e não pode ser sacrificado."})
            return
 
    estrelas_sacr = sum(
        dono["campo_monstro"][i].get("estrelas", 1)
        for i in sacrs
        if dono["campo_monstro"][i] is not None
    )
    necessario = max(0, nivel - 1)
    if estrelas_sacr < necessario:
        emit("erro", {"msg": f"Sacrifícios insuficientes. Precisa de {necessario} estrela(s), tem {estrelas_sacr}."})
        return
 
    if dono["campo_monstro"][campo_idx] is not None:
        emit("erro", {"msg": "Esse espaço de campo já está ocupado."})
        return
 
    for i in sacrs:
        if dono["campo_monstro"][i]:
            dono["cemiterio"].append(dono["campo_monstro"][i])
            dono["campo_monstro"][i] = None
 
    carta_campo = copy.deepcopy(carta)
    carta_campo["posicao"]        = posicao
    carta_campo["recem_invocado"] = True
    carta_campo["ataque_bonus"]   = 0
    carta_campo["defesa_bonus"]   = 0
    dono["campo_monstro"][campo_idx] = carta_campo
    dono["mao"].pop(mao_idx)
    dono["invocacoes"] += 1
 
    restantes = MAX_INVOCACOES - dono["invocacoes"]
    add_log(estado, f"⬆️ {dono['nome']} invocou {carta_campo['nome']} (Nv{nivel}, {posicao}). Invocações restantes: {restantes}.")
 
    msgs = aplicar_efeito_invocacao(estado, dono_idx, carta_campo)
    for m in msgs:
        add_log(estado, m)
 
    verificar_armadilha(estado, "monstro_invocado", dono_idx, {"monstro_idx": campo_idx})
    emitir_estado(sala_id)
 
@socketio.on("colocar_efeito")
def on_colocar_efeito(data):
    sala_id  = data["sala_id"]
    estado   = salas.get(sala_id)
    if not estado or estado["vencedor"] is not None:
        return
 
    dono_idx = idx_jogador(estado, request.sid)
    if dono_idx != estado["turno"]:
        emit("erro", {"msg": "Não é seu turno."})
        return
    if estado["subfase"] not in ("principal1", "principal2"):
        emit("erro", {"msg": "Só pode colocar na fase principal."})
        return
 
    dono      = estado["jogadores"][dono_idx]
    mao_idx   = data["mao_idx"]
    campo_idx = data["campo_idx"]
 
    if mao_idx >= len(dono["mao"]):
        emit("erro", {"msg": "Índice de mão inválido."})
        return
    if dono["campo_efeito"][campo_idx] is not None:
        emit("erro", {"msg": "Esse espaço já está ocupado."})
        return
 
    carta = dono["mao"][mao_idx]
    tipo  = carta.get("tipo")
    if tipo not in ("efeito", "armadilha"):
        emit("erro", {"msg": "Essa carta não é efeito nem armadilha."})
        return
 
    carta_campo = copy.deepcopy(carta)
    carta_campo["revelada"] = False
    dono["campo_efeito"][campo_idx] = carta_campo
    dono["mao"].pop(mao_idx)
 
    add_log(estado, f"🔽 {dono['nome']} posicionou uma carta virada para baixo.")
 
    emitir_estado(sala_id)
 
@socketio.on("ativar_efeito_campo")
def on_ativar_efeito_campo(data):
    sala_id  = data["sala_id"]
    estado   = salas.get(sala_id)
    if not estado or estado["vencedor"] is not None:
        return
 
    dono_idx = idx_jogador(estado, request.sid)
    if dono_idx != estado["turno"]:
        emit("erro", {"msg": "Não é seu turno."})
        return
    if estado["subfase"] not in ("principal1", "principal2"):
        emit("erro", {"msg": "Só pode ativar na fase principal."})
        return
 
    dono      = estado["jogadores"][dono_idx]
    campo_idx = data["campo_idx"]
    alvo      = data.get("alvo")
 
    if dono["ativou_efeito"]:
        emit("erro", {"msg": "Você já ativou uma carta de efeito/armadilha neste turno."})
        return
 
    slot = dono["campo_efeito"][campo_idx]
    if not slot or slot.get("tipo") != "efeito":
        emit("erro", {"msg": "Não há carta de efeito nesse espaço."})
        return
 
    pausou = verificar_armadilha(estado, "efeito_ativado", dono_idx, {"campo_idx": campo_idx, "alvo": alvo})
    if pausou:
        estado["pendente"]["efeito_para_aplicar"] = {"campo_idx": campo_idx, "alvo": alvo, "cid_banshee_check": True}
        return
 
    slot["revelada"] = True
    add_log(estado, f"📋 {dono['nome']} ativou {slot['nome']}!")
 
    msgs = aplicar_carta_efeito(estado, dono_idx, slot, alvo)
    for m in msgs:
        add_log(estado, m)
 
    dono["cemiterio"].append(slot)
    dono["campo_efeito"][campo_idx] = None
    dono["ativou_efeito"] = True
 
    emitir_estado(sala_id)
 
@socketio.on("atacar")
def on_atacar(data):
    sala_id = data["sala_id"]
    estado  = salas.get(sala_id)
    if not estado or estado["vencedor"] is not None:
        return
 
    dono_idx = idx_jogador(estado, request.sid)
    if dono_idx != estado["turno"]:
        emit("erro", {"msg": "Não é seu turno."})
        return
    if estado["subfase"] != "batalha":
        emit("erro", {"msg": "Só pode atacar na fase de batalha."})
        return
    if estado["numero_turno"] == 1:
        emit("erro", {"msg": "Não é possível atacar no primeiro turno."})
        return
 
    dono = estado["jogadores"][dono_idx]
    op   = estado["jogadores"][outro(dono_idx)]
 
    at_idx   = data["atacante_idx"]
    alvo_idx = data["alvo_idx"]
 
    atacante = dono["campo_monstro"][at_idx]
    if not atacante:
        emit("erro", {"msg": "Não há monstro nesse espaço."})
        return
    if atacante["carta_id"] in dono["ja_atacou"]:
        emit("erro", {"msg": "Esse monstro já atacou neste turno."})
        return
    if atacante.get("posicao") == "defesa":
        emit("erro", {"msg": "Monstro em defesa não pode atacar."})
        return
 
    atk_val = atacante.get("ataque", 0) + atacante.get("ataque_bonus", 0)
 
    # ── Ataque direto ──
    if alvo_idx == -1:
        monstros_op = [m for m in op["campo_monstro"] if m]
        if monstros_op:
            emit("erro", {"msg": "Oponente tem monstros em campo. Ataque um deles primeiro."})
            return
 
        # Marca como "já atacou" ANTES de verificar armadilha para evitar duplo ataque,
        # mas a armadilha "Neblina Sombria" (0c1edc5e) usa gatilho "ataque_direto" —
        # verificamos a armadilha ANTES de aplicar o dano.
        dono["ja_atacou"].append(atacante["carta_id"])
 
        pausou = verificar_armadilha(estado, "ataque_direto", dono_idx,
                                     {"dano": atk_val, "monstro_idx": at_idx, "alvo_idx": -1})
        if pausou:
            # dano será aplicado após resolver_armadilha (se não cancelado)
            emitir_estado(sala_id)
            return
 
        # Sem armadilha: aplica dano direto normalmente
        aplicar_dano(estado, outro(dono_idx), atk_val)
        add_log(estado, f"⚔️ {atacante['nome']} atacou diretamente! {atk_val} de dano a {op['nome']}.")
        venc = verificar_derrota(estado)
        if venc is not None:
            declarar_vencedor(estado, outro(venc))
            return
        emitir_estado(sala_id)
        return
 
    # ── Ataque contra monstro ──
    alvo = op["campo_monstro"][alvo_idx]
    if not alvo:
        emit("erro", {"msg": "Não há monstro nesse espaço do oponente."})
        return
 
    # Marca como "já atacou" antes de verificar armadilha
    dono["ja_atacou"].append(atacante["carta_id"])
 
    # Verifica armadilha ANTES de resolver o combate
    pausou = verificar_armadilha(estado, "ataque_declarado", dono_idx,
                                 {"monstro_idx": at_idx, "alvo_idx": alvo_idx})
    if pausou:
        emitir_estado(sala_id)
        return
 
    # Sem armadilha: resolve combate normalmente
    resolver_combate(estado, dono_idx, at_idx, alvo_idx)
    emitir_estado(sala_id)
 
def resolver_combate(estado, dono_idx, at_idx, alvo_idx):
    dono = estado["jogadores"][dono_idx]
    op   = estado["jogadores"][outro(dono_idx)]
 
    atacante = dono["campo_monstro"][at_idx]
    alvo     = op["campo_monstro"][alvo_idx]
    if not atacante or not alvo:
        return
 
    atk_val = atacante.get("ataque", 0) + atacante.get("ataque_bonus", 0)
    # garante que está na lista ja_atacou (pode já estar, mas não duplica)
    if atacante["carta_id"] not in dono["ja_atacou"]:
        dono["ja_atacou"].append(atacante["carta_id"])
 
    if alvo["posicao"] == "ataque":
        def_val = alvo.get("ataque", 0) + alvo.get("ataque_bonus", 0)
        if atk_val > def_val:
            dif = atk_val - def_val
            op["cemiterio"].append(alvo)
            op["campo_monstro"][alvo_idx] = None
            aplicar_dano(estado, outro(dono_idx), dif)
            add_log(estado, f"⚔️ {atacante['nome']} ({atk_val}) destruiu {alvo['nome']} ({def_val})! {dif} dano a {op['nome']}.")
            verificar_armadilha(estado, "monstro_destruido_combate", dono_idx, {"ataque_monstro": alvo.get("ataque",0)})
        elif atk_val < def_val:
            dif = def_val - atk_val
            dono["cemiterio"].append(atacante)
            dono["campo_monstro"][at_idx] = None
            aplicar_dano(estado, dono_idx, dif)
            add_log(estado, f"⚔️ {alvo['nome']} ({def_val}) destruiu {atacante['nome']} ({atk_val})! {dif} dano a {dono['nome']}.")
            verificar_armadilha(estado, "monstro_destruido_combate", outro(dono_idx), {"ataque_monstro": atacante.get("ataque",0)})
        else:
            dono["cemiterio"].append(atacante)
            op["cemiterio"].append(alvo)
            dono["campo_monstro"][at_idx] = None
            op["campo_monstro"][alvo_idx] = None
            add_log(estado, f"⚔️ Empate! {atacante['nome']} e {alvo['nome']} se destroem.")
    else:
        def_val = alvo.get("defesa", 0) + alvo.get("defesa_bonus", 0)
        if atk_val > def_val:
            op["cemiterio"].append(alvo)
            op["campo_monstro"][alvo_idx] = None
            add_log(estado, f"🛡️ {atacante['nome']} ({atk_val}) destruiu {alvo['nome']} em defesa ({def_val}). Sem dano.")
            verificar_armadilha(estado, "monstro_destruido_combate", dono_idx, {"ataque_monstro": alvo.get("ataque",0)})
        else:
            dono["cemiterio"].append(atacante)
            dono["campo_monstro"][at_idx] = None
            add_log(estado, f"🛡️ {alvo['nome']} em defesa ({def_val}) resistiu! {atacante['nome']} destruído.")
            verificar_armadilha(estado, "monstro_destruido_combate", outro(dono_idx), {"ataque_monstro": atacante.get("ataque",0)})
 
    venc = verificar_derrota(estado)
    if venc is not None:
        declarar_vencedor(estado, outro(venc))
 
@socketio.on("mudar_posicao")
def on_mudar_posicao(data):
    sala_id  = data["sala_id"]
    estado   = salas.get(sala_id)
    if not estado or estado["vencedor"] is not None:
        return
 
    dono_idx = idx_jogador(estado, request.sid)
    if dono_idx != estado["turno"]:
        emit("erro", {"msg": "Não é seu turno."})
        return
    if estado["subfase"] not in ("principal1", "principal2"):
        emit("erro", {"msg": "Só pode mudar posição na fase principal."})
        return
 
    dono      = estado["jogadores"][dono_idx]
    campo_idx = data["campo_idx"]
    slot      = dono["campo_monstro"][campo_idx]
    if not slot:
        emit("erro", {"msg": "Não há monstro nesse espaço."})
        return
    if slot.get("recem_invocado"):
        emit("erro", {"msg": "Monstro recém-invocado não pode mudar de posição."})
        return
    if slot.get("mudou_posicao"):
        emit("erro", {"msg": "Esse monstro já mudou de posição neste turno."})
        return
 
    nova = "defesa" if slot["posicao"] == "ataque" else "ataque"
    slot["posicao"] = nova
    slot["mudou_posicao"] = True
    add_log(estado, f"🔄 {dono['nome']} colocou {slot['nome']} em modo {nova}.")
    emitir_estado(sala_id)
 
@socketio.on("descartar_voluntario")
def on_descartar_voluntario(data):
    sala_id  = data["sala_id"]
    estado   = salas.get(sala_id)
    if not estado or estado["vencedor"] is not None:
        return
 
    dono_idx = idx_jogador(estado, request.sid)
    if dono_idx != estado["turno"]:
        emit("erro", {"msg": "Não é seu turno."})
        return
    if estado["subfase"] not in ("principal1", "principal2"):
        emit("erro", {"msg": "Só pode descartar na fase principal."})
        return
 
    dono      = estado["jogadores"][dono_idx]
    campo_idx = data["campo_idx"]
    slot      = dono["campo_efeito"][campo_idx]
 
    if not slot or slot.get("tipo") not in ("efeito", "armadilha"):
        emit("erro", {"msg": "Não há carta de efeito/armadilha nesse espaço para descartar."})
        return
    if dono.get("descartou_voluntario"):
        emit("erro", {"msg": "Você já descartou voluntariamente neste turno."})
        return
 
    dono["cemiterio"].append(slot)
    dono["campo_efeito"][campo_idx] = None
    dono["descartou_voluntario"] = True
 
    r = comprar_carta(dono)
    if r:
        add_log(estado, r)
    add_log(estado, f"🗑️ {dono['nome']} descartou {slot['nome']} e comprou 1 carta.")
    emitir_estado(sala_id)
 
 
def _verificar_excesso_mao(estado, dono, sala_id):
    excesso = len(dono["mao"]) - MAX_MAO
    if excesso > 0:
        add_log(estado, f"⚠️ {dono['nome']} deve descartar {excesso} carta(s) da mão.")
        socketio.emit("descartar_fim_turno", {"quantidade": excesso}, room=dono["sid"])
        emitir_estado(sala_id)
    else:
        finalizar_turno(estado)
 
 
@socketio.on("avancar_subfase")
def on_avancar_subfase(data):
    sala_id = data["sala_id"]
    estado  = salas.get(sala_id)
    if not estado or estado["vencedor"] is not None:
        return
 
    dono_idx = idx_jogador(estado, request.sid)
    if dono_idx != estado["turno"]:
        emit("erro", {"msg": "Não é seu turno."})
        return
 
    subfase = estado["subfase"]
    dono    = estado["jogadores"][dono_idx]
 
    if subfase == "principal1":
        if estado["numero_turno"] == 1 and dono_idx == estado["turno"]:
            estado["subfase"] = "principal2"
            add_log(estado, f"⚔️ [Turno 1 — sem batalha] → Fase Principal 2")
        else:
            estado["subfase"] = "batalha"
            add_log(estado, f"⚔️ {dono['nome']} — Fase de Batalha")
 
    elif subfase == "batalha":
        estado["subfase"] = "principal2"
        add_log(estado, f"📋 {dono['nome']} — Fase Principal 2")
 
    elif subfase == "principal2":
        estado["subfase"] = "fim"
        _verificar_excesso_mao(estado, dono, sala_id)
        return
 
    elif subfase == "fim":
        excesso = len(dono["mao"]) - MAX_MAO
        if excesso > 0:
            add_log(estado, f"⚠️ {dono['nome']} ainda precisa descartar {excesso} carta(s).")
            socketio.emit("descartar_fim_turno", {"quantidade": excesso}, room=dono["sid"])
            emitir_estado(sala_id)
            return
        finalizar_turno(estado)
        return
 
    emitir_estado(sala_id)
 
 
@socketio.on("descartar_mao_fim_turno")
def on_descartar_mao_fim_turno(data):
    sala_id = data["sala_id"]
    estado  = salas.get(sala_id)
    if not estado:
        return
 
    dono_idx = idx_jogador(estado, request.sid)
    dono     = estado["jogadores"][dono_idx]
 
    indices = sorted(data.get("indices", []), reverse=True)
    for i in indices:
        if i < len(dono["mao"]):
            dono["cemiterio"].append(dono["mao"].pop(i))
 
    excesso = len(dono["mao"]) - MAX_MAO
    if excesso > 0:
        socketio.emit("descartar_fim_turno", {"quantidade": excesso}, room=dono["sid"])
        emitir_estado(sala_id)
        return
 
    finalizar_turno(estado)
 
 
@socketio.on("responder_armadilha")
def on_responder_armadilha(data):
    sala_id = data["sala_id"]
    estado  = salas.get(sala_id)
    if not estado or not estado.get("pendente"):
        return
    resolver_armadilha(estado, data.get("ativar", False))
 
@socketio.on("resolver_lich_supremo")
def on_resolver_lich_supremo(data):
    sala_id = data["sala_id"]
    estado  = salas.get(sala_id)
    if not estado or not estado.get("pendente"):
        return
    if estado["pendente"].get("tipo") != "lich_supremo":
        return
 
    pend     = estado["pendente"]
    estado["pendente"] = None
    dono_idx = pend["dono_idx"]
    op_idx   = outro(dono_idx)
    op       = estado["jogadores"][op_idx]
 
    tipo_alvo = data.get("tipo_alvo")
    alvo_idx  = data.get("alvo_idx")
 
    if tipo_alvo == "monstro" and op["campo_monstro"][alvo_idx]:
        destruido = op["campo_monstro"][alvo_idx]
        op["cemiterio"].append(destruido)
        op["campo_monstro"][alvo_idx] = None
        add_log(estado, f"💀 Lich Supremo destruiu {destruido['nome']}!")
    elif tipo_alvo == "efeito" and op["campo_efeito"][alvo_idx]:
        destruido = op["campo_efeito"][alvo_idx]
        op["cemiterio"].append(destruido)
        op["campo_efeito"][alvo_idx] = None
        add_log(estado, f"💀 Lich Supremo destruiu {destruido['nome']}!")
 
    emitir_estado(sala_id)
 
def finalizar_turno(estado):
    turno_antigo = estado["turno"]
    dono         = estado["jogadores"][turno_antigo]
 
    for slot in dono["campo_monstro"]:
        if slot:
            slot["recem_invocado"] = False
            slot["mudou_posicao"]  = False
            slot.pop("ataque_bonus", None)
            slot.pop("defesa_bonus", None)
    dono["ja_atacou"]            = []
    dono["invocacoes"]           = 0
    dono["ativou_efeito"]        = False
    dono["descartou_voluntario"] = False
 
    proximo = outro(turno_antigo)
    estado["turno"]   = proximo
    estado["subfase"] = "compra"
 
    if proximo == 0:
        estado["numero_turno"] += 1
 
    prox_jog = estado["jogadores"][proximo]
    add_log(estado, f"─────────────────────────────────────")
    add_log(estado, f"▶ Turno {estado['numero_turno']} — {prox_jog['nome']} — Compra")
 
    r = comprar_carta(prox_jog)
    if r:
        add_log(estado, r)
        venc_idx = next(
            (i for i, j in enumerate(estado["jogadores"]) if ("DERROTA" in r and j["nome"] in r)), None
        )
        if venc_idx is not None:
            declarar_vencedor(estado, outro(venc_idx))
            return
 
    estado["subfase"] = "principal1"
    add_log(estado, f"📋 {prox_jog['nome']} — Fase Principal 1")
    emitir_estado(estado["sala_id"])
 
# ── Inicialização ──────────────────────────────────────────────────────────────
 
if __name__ == "__main__":
    if not os.path.exists(CARTAS_DB_PATH):
        print(f"[ERRO] cartas.json não encontrado em: {CARTAS_DB_PATH}")
        exit(1)
    if not os.path.exists(PASTA_IMAGENS):
        print(f"[AVISO] Pasta de imagens não encontrada: {PASTA_IMAGENS}")
    print("Servidor iniciado em http://localhost:8080")
    socketio.run(app, host="0.0.0.0", port=8080, debug=False)