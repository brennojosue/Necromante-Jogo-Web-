from tinydb import TinyDB, Query
import uuid
import asyncio
import random
import json
import os
import threading
 
DB_PATH = os.path.join(os.path.dirname(__file__), "cartas.json")
 
# ── Migração automática ───────────────────────────────────────────────────────
 
def _migrar_se_necessario():
    if not os.path.exists(DB_PATH):
        return
    with open(DB_PATH, encoding="utf-8") as f:
        try:
            dados = json.load(f)
        except json.JSONDecodeError:
            print("[AVISO] cartas.json inválido — será recriado do zero.")
            os.remove(DB_PATH)
            return
    if isinstance(dados, list):
        print(f"[INFO] Migrando cartas.json do formato legado para TinyDB ({len(dados)} cartas)...")
        cartas_migradas = {}
        for i, carta in enumerate(dados, start=1):
            carta.setdefault("carta_id", str(uuid.uuid4())[:8])
            cartas_migradas[str(i)] = carta
        novo_formato = {
            "_default": {},
            "usuarios": {},
            "catalogo": cartas_migradas,
        }
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump(novo_formato, f, indent=2, ensure_ascii=False)
        print("[INFO] Migração concluída.")
 
_migrar_se_necessario()
 
db = TinyDB(DB_PATH, indent=2, ensure_ascii=False, encoding="utf-8")
usuarios     = db.table("usuarios")
catalogo_col = db.table("catalogo")
U = Query()
 
# ── Banco do Codex Nivalandhur ────────────────────────────────────────────────
 
CODEX_DB_PATH  = r"C:\Users\brenn\OneDrive\Desktop\Bots\Codex Nivalandhur\economia.json"
PRECO_FICHA_PO = 10
 
_codex_lock = threading.Lock()
 
def _codex_disponivel() -> bool:
    return os.path.exists(CODEX_DB_PATH)
 
def _debitar_po_codex(discord_id: int, quantidade_po: int) -> str:
    """
    Tenta debitar `quantidade_po` PO do usuário no banco do Codex.
    Retorna 'ok', 'sem_saldo' ou 'usuario_nao_encontrado'.
    Executado em executor para não bloquear o event loop.
    """
    with _codex_lock:
        codex_db = TinyDB(CODEX_DB_PATH, indent=2, ensure_ascii=False, encoding="utf-8")
        economia = codex_db.table("usuarios")
        UC       = Query()
        doc      = economia.get(UC.discord_id == discord_id)
        if not doc:
            codex_db.close()
            return "usuario_nao_encontrado"
        po_atual = doc.get("PO", 0)
        if po_atual < quantidade_po:
            codex_db.close()
            return "sem_saldo"
        economia.update({"PO": po_atual - quantidade_po}, UC.discord_id == discord_id)
        codex_db.close()
        return "ok"
 
# ── Seed do catálogo ──────────────────────────────────────────────────────────
 
def _seed_catalogo():
    total = catalogo_col.count(U.numero.exists())
    if total == 0:
        print("[AVISO] Catálogo vazio após migração — nenhuma carta disponível.")
    else:
        print(f"[INFO] Catálogo pronto ({total} cartas).")
 
_seed_catalogo()
 
async def _run(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args))
 
# ── Fichas ────────────────────────────────────────────────────────────────────
 
async def novo_usuario(usuario):
    existe = await _run(usuarios.contains, U.discord_id == usuario.id)
    if not existe:
        await _run(usuarios.insert, {
            "discord_id": usuario.id,
            "fichas": 0,
            "bolso": [],
            "caixa": [],
            "imagem": None
        })
 
async def get_usuario(usuario):
    await novo_usuario(usuario)
    return await _run(usuarios.get, U.discord_id == usuario.id)
 
async def adicionar_fichas(usuario, quantidade: int):
    doc = await get_usuario(usuario)
    await _run(usuarios.update, {"fichas": doc.get("fichas", 0) + quantidade}, U.discord_id == usuario.id)
 
async def gastar_ficha(usuario) -> bool:
    doc = await get_usuario(usuario)
    if doc.get("fichas", 0) < 1:
        return False
    await _run(usuarios.update, {"fichas": doc["fichas"] - 1}, U.discord_id == usuario.id)
    return True
 
async def comprar_ficha_com_po(usuario) -> str:
    """
    Debita 10 PO do Codex e credita 1 ficha no Necromante.
    Retorna 'ok', 'sem_saldo', 'usuario_nao_encontrado' ou 'codex_indisponivel'.
    """
    if not _codex_disponivel():
        return "codex_indisponivel"
    resultado = await _run(_debitar_po_codex, usuario.id, PRECO_FICHA_PO)
    if resultado == "ok":
        await adicionar_fichas(usuario, 1)
    return resultado
 
async def cadastrar_imagem_usuario(usuario, url):
    await novo_usuario(usuario)
    await _run(usuarios.update, {"imagem": url}, U.discord_id == usuario.id)
 
# ── Catálogo ──────────────────────────────────────────────────────────────────
 
async def cadastrar_carta(dados: dict) -> dict:
    carta = {"carta_id": str(uuid.uuid4())[:8], **dados}
    await _run(catalogo_col.insert, carta)
    return carta
 
async def listar_catalogo(tipo=None):
    todas = await _run(catalogo_col.all)
    if tipo:
        todas = [c for c in todas if c.get("tipo", "").lower() == tipo.lower()]
    return sorted(todas, key=lambda c: c.get("numero", 0))
 
async def buscar_carta_catalogo(nome):
    return await _run(catalogo_col.get, U.nome.test(lambda n: n.lower() == nome.lower()))
 
# ── Pacotes ───────────────────────────────────────────────────────────────────
 
async def sortear_pacote():
    """Sorteia 4 cartas: slots 1-2 do pool de monstros, slots 3-4 do catálogo completo."""
    todas    = await _run(catalogo_col.all)
    monstros = [c for c in todas if c.get("tipo") in ("monstro", "monstro_efeito")]
 
    if not monstros:
        monstros = todas
 
    def sortear(pool):
        pesos = [c.get("chance", 1.0) for c in pool]
        return random.choices(pool, weights=pesos, k=1)[0]
 
    return [
        sortear(monstros),
        sortear(monstros),
        sortear(todas),
        sortear(todas),
    ]
 
# ── Deck ──────────────────────────────────────────────────────────────────────
 
def total_bolso(doc):
    return sum(c["quantidade"] for c in doc.get("bolso", []))
 
async def adicionar_carta_deck(usuario, carta: dict, quantidade: int = 1):
    """Adiciona ao bolso se houver espaço, senão à caixa. Retorna (para_bolso, para_caixa)."""
    doc        = await get_usuario(usuario)
    bolso      = doc.get("bolso", [])
    caixa      = doc.get("caixa", [])
    espaco     = 40 - total_bolso(doc)
    para_bolso = min(quantidade, espaco)
    para_caixa = quantidade - para_bolso
 
    if para_bolso > 0:
        encontrado = False
        for entry in bolso:
            if entry["carta_id"] == carta["carta_id"]:
                entry["quantidade"] += para_bolso
                encontrado = True
                break
        if not encontrado:
            bolso.append({"carta_id": carta["carta_id"], "nome": carta["nome"], "quantidade": para_bolso})
 
    if para_caixa > 0:
        encontrado = False
        for entry in caixa:
            if entry["carta_id"] == carta["carta_id"]:
                entry["quantidade"] += para_caixa
                encontrado = True
                break
        if not encontrado:
            caixa.append({"carta_id": carta["carta_id"], "nome": carta["nome"], "quantidade": para_caixa})
 
    await _run(usuarios.update, {"bolso": bolso, "caixa": caixa}, U.discord_id == usuario.id)
    return para_bolso, para_caixa
 
async def mover_bolso_para_caixa(usuario, nome_carta: str, quantidade: int = 1) -> bool:
    doc   = await get_usuario(usuario)
    bolso = doc.get("bolso", [])
    caixa = doc.get("caixa", [])
 
    for i, c in enumerate(bolso):
        if c["nome"].lower() == nome_carta.lower():
            if c["quantidade"] < quantidade:
                return False
            if c["quantidade"] == quantidade:
                bolso.pop(i)
            else:
                bolso[i]["quantidade"] -= quantidade
            encontrado = False
            for entry in caixa:
                if entry["carta_id"] == c["carta_id"]:
                    entry["quantidade"] += quantidade
                    encontrado = True
                    break
            if not encontrado:
                caixa.append({"carta_id": c["carta_id"], "nome": c["nome"], "quantidade": quantidade})
            await _run(usuarios.update, {"bolso": bolso, "caixa": caixa}, U.discord_id == usuario.id)
            return True
    return False
 
async def mover_caixa_para_bolso(usuario, nome_carta: str, quantidade: int = 1) -> str:
    """Retorna 'ok', 'sem_espaco' ou 'sem_carta'."""
    doc    = await get_usuario(usuario)
    bolso  = doc.get("bolso", [])
    caixa  = doc.get("caixa", [])
    espaco = 40 - total_bolso(doc)
 
    if espaco < quantidade:
        return "sem_espaco"
 
    for i, c in enumerate(caixa):
        if c["nome"].lower() == nome_carta.lower():
            if c["quantidade"] < quantidade:
                return "sem_carta"
            if c["quantidade"] == quantidade:
                caixa.pop(i)
            else:
                caixa[i]["quantidade"] -= quantidade
            encontrado = False
            for entry in bolso:
                if entry["carta_id"] == c["carta_id"]:
                    entry["quantidade"] += quantidade
                    encontrado = True
                    break
            if not encontrado:
                bolso.append({"carta_id": c["carta_id"], "nome": c["nome"], "quantidade": quantidade})
            await _run(usuarios.update, {"bolso": bolso, "caixa": caixa}, U.discord_id == usuario.id)
            return "ok"
    return "sem_carta"
 
async def remover_carta_deck(usuario, nome_carta: str, quantidade: int = 1, origem: str = "bolso") -> bool:
    doc   = await get_usuario(usuario)
    lista = doc.get(origem, [])
    for i, c in enumerate(lista):
        if c["nome"].lower() == nome_carta.lower():
            if c["quantidade"] < quantidade:
                return False
            if c["quantidade"] == quantidade:
                lista.pop(i)
            else:
                lista[i]["quantidade"] -= quantidade
            await _run(usuarios.update, {origem: lista}, U.discord_id == usuario.id)
            return True
    return False