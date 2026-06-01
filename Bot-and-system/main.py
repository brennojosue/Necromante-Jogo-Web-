import discord
from discord import app_commands
from dotenv import load_dotenv
import os
import logging
from database import (
    get_usuario,
    adicionar_fichas, gastar_ficha, comprar_ficha_com_po,
    cadastrar_imagem_usuario,
    cadastrar_carta,
    listar_catalogo, buscar_carta_catalogo,
    sortear_pacote,
    adicionar_carta_deck, mover_bolso_para_caixa, mover_caixa_para_bolso,
    remover_carta_deck, total_bolso,
)
 
logging.getLogger("discord").setLevel(logging.CRITICAL)
 
load_dotenv()
 
class Necromante(discord.Client):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
 
    async def setup_hook(self):
        await self.tree.sync()
 
    async def on_ready(self):
        print(f"bot {self.user} ativo")
 
bot = Necromante()
 
# ── Erro de permissão ─────────────────────────────────────────────────────────
 
@bot.tree.error
async def on_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Você não tem permissão para usar esse comando."
    elif isinstance(error, app_commands.CommandInvokeError):
        print(f"[ERRO] {interaction.command.name}: {error.original}")
        msg = f"❌ Erro interno no comando `{interaction.command.name}`. Verifique o terminal."
    else:
        print(f"[ERRO] {error}")
        msg = "❌ Ocorreu um erro inesperado."
 
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass
 
# ── Utilitários de embed ──────────────────────────────────────────────────────
 
ITENS_POR_PAGINA = 10
 
TIPO_LABEL = {
    "monstro":        "Monstro",
    "monstro_efeito": "Monstro com Efeito",
    "efeito":         "Carta de Efeito",
    "armadilha":      "Carta Armadilha",
}
 
TIPO_COR = {
    "monstro":        discord.Color.from_rgb(139, 0, 0),
    "monstro_efeito": discord.Color.from_rgb(128, 0, 128),
    "efeito":         discord.Color.from_rgb(0, 100, 180),
    "armadilha":      discord.Color.from_rgb(180, 100, 0),
}
 
ESTRELAS = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}
 
def montar_embed_carta(carta: dict) -> discord.Embed:
    tipo  = carta.get("tipo", "")
    cor   = TIPO_COR.get(tipo, discord.Color.dark_gray())
    label = TIPO_LABEL.get(tipo, tipo)
    embed = discord.Embed(title=f"#{carta.get('numero', '?')} — {carta['nome']}", color=cor)
 
    if carta.get("imagem"):
        embed.set_thumbnail(url=carta["imagem"])
 
    embed.add_field(name="Tipo",     value=label,                      inline=True)
    embed.add_field(name="Raridade", value=carta.get("raridade", "—"), inline=True)
 
    if tipo in ("monstro", "monstro_efeito"):
        estrelas = carta.get("estrelas") or 1
        embed.add_field(name="Nível",  value=ESTRELAS.get(estrelas, "⭐" * estrelas), inline=True)
        embed.add_field(name="Ataque", value=str(carta.get("ataque", "—")), inline=True)
        embed.add_field(name="Defesa", value=str(carta.get("defesa", "—")), inline=True)
        embed.add_field(name="\u200b", value="\u200b",                      inline=True)
 
    if carta.get("descricao"):
        embed.add_field(name="Descrição", value=carta["descricao"], inline=False)
 
    if tipo == "armadilha" and carta.get("gatilho"):
        embed.add_field(name="Gatilho", value=carta["gatilho"], inline=False)
 
    if carta.get("efeito"):
        embed.add_field(name="Efeito", value=carta["efeito"], inline=False)
 
    return embed
 
 
def montar_deck_embed(membro: discord.Member, doc: dict, secao: str = "bolso") -> discord.Embed:
    lista  = doc.get(secao, [])
    titulo = "Bolso (deck principal)" if secao == "bolso" else "Caixa de Cartas"
    cor    = discord.Color.dark_red() if secao == "bolso" else discord.Color.dark_gray()
    embed  = discord.Embed(title=f"{membro.name} — {titulo}", color=cor)
 
    imagem = doc.get("imagem") or membro.display_avatar.url
    embed.set_thumbnail(url=imagem)
 
    if lista:
        texto = "\n".join(f"{c['quantidade']}x {c['nome']}" for c in lista)
    else:
        texto = "_Nenhuma carta._"
 
    embed.add_field(name="Cartas", value=texto, inline=False)
 
    if secao == "bolso":
        embed.set_footer(text=f"{total_bolso(doc)}/40 cartas no bolso")
 
    embed.add_field(name="🎟️ Fichas", value=str(doc.get("fichas", 0)), inline=True)
    return embed
 
 
def montar_pagina_catalogo(itens: list, pagina: int) -> discord.Embed:
    total_paginas = max(1, -(-len(itens) // ITENS_POR_PAGINA))
    inicio = pagina * ITENS_POR_PAGINA
    fatia  = itens[inicio:inicio + ITENS_POR_PAGINA]
 
    embed = discord.Embed(title="📖 Catálogo — Edição I", color=discord.Color.dark_purple())
    embed.set_footer(text=f"Página {pagina + 1} de {total_paginas}  •  {len(itens)} cartas no total")
 
    if not fatia:
        embed.description = "_Nenhuma carta cadastrada._"
        return embed
 
    nomes     = "\n".join(f"#{c.get('numero','?')} {c['nome']}" for c in fatia)
    tipos     = "\n".join(TIPO_LABEL.get(c.get("tipo",""), c.get("tipo","")) for c in fatia)
    raridades = "\n".join(c.get("raridade", "—") for c in fatia)
 
    embed.add_field(name="Carta",    value=nomes,     inline=True)
    embed.add_field(name="Tipo",     value=tipos,     inline=True)
    embed.add_field(name="Raridade", value=raridades, inline=True)
    return embed
 
 
async def _processar_pacote(usuario: discord.Member, cartas: list):
    linhas_bolso = []
    linhas_caixa = []
 
    for carta in cartas:
        pb, pc = await adicionar_carta_deck(usuario, carta, 1)
        tipo_label = TIPO_LABEL.get(carta.get("tipo", ""), carta.get("tipo", ""))
        raridade   = carta.get("raridade", "")
        linha      = f"**{carta['nome']}** _{tipo_label} • {raridade}_"
        if pb > 0:
            linhas_bolso.append(f"🂠 {linha}")
        else:
            linhas_caixa.append(f"📦 {linha} _(caixa — bolso cheio)_")
 
    doc    = await get_usuario(usuario)
    footer = f"Bolso de {usuario.name}: {total_bolso(doc)}/40 cartas"
    return linhas_bolso + linhas_caixa, footer
 
 
class PaginaView(discord.ui.View):
    def __init__(self, itens: list, build_embed):
        super().__init__(timeout=120)
        self.itens       = itens
        self.build_embed = build_embed
        self.pagina      = 0
        self.total       = max(1, -(-len(itens) // ITENS_POR_PAGINA))
        self._atualizar_botoes()
 
    def _atualizar_botoes(self):
        self.btn_anterior.disabled = self.pagina == 0
        self.btn_proxima.disabled  = self.pagina >= self.total - 1
 
    def embed_atual(self) -> discord.Embed:
        return self.build_embed(self.itens, self.pagina)
 
    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.secondary)
    async def btn_anterior(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pagina -= 1
        self._atualizar_botoes()
        await interaction.response.edit_message(embed=self.embed_atual(), view=self)
 
    @discord.ui.button(label="Próxima ▶", style=discord.ButtonStyle.secondary)
    async def btn_proxima(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pagina += 1
        self._atualizar_botoes()
        await interaction.response.edit_message(embed=self.embed_atual(), view=self)
 
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
 
# ── Autocomplete ──────────────────────────────────────────────────────────────
 
async def ac_catalogo(interaction: discord.Interaction, current: str):
    itens = await listar_catalogo()
    return [
        app_commands.Choice(name=f"#{c.get('numero','?')} {c['nome']}", value=c["nome"])
        for c in itens
        if current.lower() in c["nome"].lower()
    ][:25]
 
async def ac_bolso(interaction: discord.Interaction, current: str):
    doc = await get_usuario(interaction.user)
    return [
        app_commands.Choice(name=f"{c['nome']} (x{c['quantidade']})", value=c["nome"])
        for c in doc.get("bolso", [])
        if current.lower() in c["nome"].lower()
    ][:25]
 
async def ac_caixa(interaction: discord.Interaction, current: str):
    doc = await get_usuario(interaction.user)
    return [
        app_commands.Choice(name=f"{c['nome']} (x{c['quantidade']})", value=c["nome"])
        for c in doc.get("caixa", [])
        if current.lower() in c["nome"].lower()
    ][:25]
 
async def ac_bolso_alvo(interaction: discord.Interaction, current: str):
    resolved = interaction.namespace.usuario
    if not resolved:
        return []
    doc = await get_usuario(resolved)
    return [
        app_commands.Choice(name=f"{c['nome']} (x{c['quantidade']})", value=c["nome"])
        for c in doc.get("bolso", [])
        if current.lower() in c["nome"].lower()
    ][:25]
 
async def ac_tipo(interaction: discord.Interaction, current: str):
    opcoes = ["monstro", "monstro_efeito", "efeito", "armadilha"]
    return [
        app_commands.Choice(name=TIPO_LABEL.get(op, op), value=op)
        for op in opcoes
        if current.lower() in op.lower()
    ]
 
# ── Comandos gerais ───────────────────────────────────────────────────────────
 
@bot.tree.command(name="fichas", description="Ver suas fichas")
async def fichas(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    doc = await get_usuario(interaction.user)
    quantidade = doc.get("fichas", 0)
    await interaction.followup.send(
        f"🎟️ **{interaction.user.name}** tem **{quantidade}** ficha(s)."
    )
 
 
@bot.tree.command(name="comprar_ficha", description="Comprar 1 ficha por 10 PO")
async def comprar_ficha(interaction: discord.Interaction):
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.errors.NotFound:
        return
 
    resultado = await comprar_ficha_com_po(interaction.user)
 
    mensagens = {
        "ok":                     "✅ Ficha comprada! **10 PO** debitados do seu inventário.",
        "sem_saldo":              "❌ Você não tem PO suficiente. São necessários **10 PO**.",
        "usuario_nao_encontrado": "❌ Você não tem cadastro no sistema de economia.",
        "codex_indisponivel":     "❌ Sistema de economia indisponível no momento.",
    }
 
    await interaction.followup.send(
        mensagens.get(resultado, "❌ Erro desconhecido."), ephemeral=True
    )
 
 
@bot.tree.command(name="comprar_pacote", description="Comprar um pacote de 4 cartas por 1 ficha")
async def comprar_pacote(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
 
    sucesso = await gastar_ficha(interaction.user)
    if not sucesso:
        await interaction.followup.send(
            "❌ Você não tem fichas suficientes. Use `/comprar_ficha` para obter fichas com PO."
        )
        return
 
    cartas = await sortear_pacote()
    embed  = discord.Embed(
        title="🃏 Pacote Aberto!",
        description=f"{interaction.user.mention} abriu um pacote e recebeu:",
        color=discord.Color.dark_purple()
    )
    todas_linhas, footer = await _processar_pacote(interaction.user, cartas)
    embed.add_field(name="Cartas recebidas", value="\n".join(todas_linhas), inline=False)
    embed.set_footer(text=footer)
    await interaction.followup.send(embed=embed)
 
 
@bot.tree.command(name="catalogo", description="Ver todas as cartas cadastradas")
@app_commands.autocomplete(tipo=ac_tipo)
async def catalogo(interaction: discord.Interaction, tipo: str = None):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    itens = await listar_catalogo(tipo)
    view  = PaginaView(itens, montar_pagina_catalogo)
    await interaction.followup.send(embed=view.embed_atual(), view=view)
 
 
@bot.tree.command(name="carta", description="Ver detalhes de uma carta específica")
@app_commands.autocomplete(nome=ac_catalogo)
async def carta(interaction: discord.Interaction, nome: str):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    c = await buscar_carta_catalogo(nome)
    if not c:
        await interaction.followup.send(f"❌ **{nome}** não encontrada no catálogo.")
        return
    await interaction.followup.send(embed=montar_embed_carta(c))
 
 
@bot.tree.command(name="deck", description="Ver seu deck (bolso e caixa)")
async def deck(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    doc = await get_usuario(interaction.user)
    embed_bolso = montar_deck_embed(interaction.user, doc, "bolso")
    embed_caixa = montar_deck_embed(interaction.user, doc, "caixa")
    await interaction.followup.send(embeds=[embed_bolso, embed_caixa])
 
 
@bot.tree.command(name="mover_para_caixa", description="Mover uma carta do bolso para a caixa")
@app_commands.autocomplete(carta=ac_bolso)
async def mover_para_caixa(interaction: discord.Interaction, carta: str, quantidade: int = 1):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    if quantidade < 1:
        await interaction.followup.send("❌ A quantidade deve ser pelo menos 1.")
        return
    ok = await mover_bolso_para_caixa(interaction.user, carta, quantidade)
    if not ok:
        await interaction.followup.send(f"❌ Você não tem **{quantidade}x {carta}** no bolso.")
        return
    await interaction.followup.send(f"✅ **{quantidade}x {carta}** movida(s) do bolso para a caixa.")
 
 
@bot.tree.command(name="mover_para_bolso", description="Mover uma carta da caixa para o bolso")
@app_commands.autocomplete(carta=ac_caixa)
async def mover_para_bolso(interaction: discord.Interaction, carta: str, quantidade: int = 1):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    if quantidade < 1:
        await interaction.followup.send("❌ A quantidade deve ser pelo menos 1.")
        return
    resultado = await mover_caixa_para_bolso(interaction.user, carta, quantidade)
    if resultado == "sem_espaco":
        doc    = await get_usuario(interaction.user)
        espaco = 40 - total_bolso(doc)
        await interaction.followup.send(
            f"❌ Bolso sem espaço suficiente. Você tem {espaco} slot(s) livre(s) e tentou mover {quantidade}."
        )
    elif resultado == "sem_carta":
        await interaction.followup.send(f"❌ Você não tem **{quantidade}x {carta}** na caixa.")
    else:
        await interaction.followup.send(f"✅ **{quantidade}x {carta}** movida(s) da caixa para o bolso.")
 
# ── Comandos de moderador ─────────────────────────────────────────────────────
 
@bot.tree.command(name="cadastrar_carta", description="[MOD] Cadastrar uma nova carta no catálogo")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.autocomplete(tipo=ac_tipo)
async def cadastrar_carta_cmd(
    interaction: discord.Interaction,
    numero: int,
    nome: str,
    tipo: str,
    raridade: str,
    chance: float,
    descricao: str = None,
    efeito: str = None,
    gatilho: str = None,
    ataque: int = None,
    defesa: int = None,
    estrelas: int = None,
    chance_monstro: float = None,
):
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.errors.NotFound:
        return
 
    dados = {
        "numero":   numero,
        "nome":     nome,
        "tipo":     tipo,
        "raridade": raridade,
        "chance":   chance,
        "imagem":   None,
    }
    if descricao:                  dados["descricao"]      = descricao
    if efeito:                     dados["efeito"]         = efeito
    if gatilho:                    dados["gatilho"]        = gatilho
    if ataque is not None:         dados["ataque"]         = ataque
    if defesa is not None:         dados["defesa"]         = defesa
    if estrelas is not None:       dados["estrelas"]       = estrelas
    if chance_monstro is not None: dados["chance_monstro"] = chance_monstro
 
    carta_doc = await cadastrar_carta(dados)
    await interaction.followup.send(
        f"✅ **#{numero} {nome}** cadastrada no catálogo "
        f"(tipo: {TIPO_LABEL.get(tipo, tipo)}, raridade: {raridade}, id: `{carta_doc['carta_id']}`).",
        ephemeral=True
    )
 
 
@bot.tree.command(name="dar_fichas", description="[MOD] Dar fichas para um usuário")
@app_commands.checks.has_permissions(manage_guild=True)
async def dar_fichas(interaction: discord.Interaction, usuario: discord.Member, quantidade: int):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    if quantidade < 1:
        await interaction.followup.send("❌ A quantidade deve ser pelo menos 1.")
        return
    await adicionar_fichas(usuario, quantidade)
    doc = await get_usuario(usuario)
    await interaction.followup.send(
        f"✅ **{quantidade}** ficha(s) adicionada(s) para {usuario.mention}.\n"
        f"🎟️ Total atual: **{doc.get('fichas', 0)}** ficha(s)."
    )
 
 
@bot.tree.command(name="recompensa_pacote", description="[MOD] Dar um pacote de cartas para um usuário (sem custo)")
@app_commands.checks.has_permissions(manage_guild=True)
async def recompensa_pacote(interaction: discord.Interaction, usuario: discord.Member):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
 
    cartas = await sortear_pacote()
    embed  = discord.Embed(
        title="🎁 Pacote de Recompensa!",
        description=f"{usuario.mention} recebeu um pacote de {interaction.user.mention}:",
        color=discord.Color.gold()
    )
    todas_linhas, footer = await _processar_pacote(usuario, cartas)
    embed.add_field(name="Cartas recebidas", value="\n".join(todas_linhas), inline=False)
    embed.set_footer(text=footer)
    await interaction.followup.send(embed=embed)
 
 
@bot.tree.command(name="recompensa_carta", description="[MOD] Dar uma carta específica do catálogo para um usuário")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.autocomplete(carta=ac_catalogo)
async def recompensa_carta(interaction: discord.Interaction, usuario: discord.Member, carta: str, quantidade: int = 1):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    if quantidade < 1:
        await interaction.followup.send("❌ A quantidade deve ser pelo menos 1.")
        return
    carta_doc = await buscar_carta_catalogo(carta)
    if not carta_doc:
        await interaction.followup.send(f"❌ **{carta}** não encontrada no catálogo.")
        return
    pb, pc = await adicionar_carta_deck(usuario, carta_doc, quantidade)
    msg = f"✅ **{quantidade}x {carta_doc['nome']}** dado(s) para {usuario.mention}."
    if pc > 0:
        msg += f"\n⚠️ {pc} carta(s) foram para a **caixa** (bolso cheio)."
    await interaction.followup.send(msg)
 
 
@bot.tree.command(name="ver_deck", description="[MOD] Ver o deck de um jogador")
@app_commands.checks.has_permissions(manage_guild=True)
async def ver_deck(interaction: discord.Interaction, usuario: discord.Member):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    doc = await get_usuario(usuario)
    embed_bolso = montar_deck_embed(usuario, doc, "bolso")
    embed_caixa = montar_deck_embed(usuario, doc, "caixa")
    await interaction.followup.send(embeds=[embed_bolso, embed_caixa])
 
 
@bot.tree.command(name="destruir_carta", description="[MOD] Remover uma carta do deck de um jogador")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.autocomplete(carta=ac_bolso_alvo)
async def destruir_carta(interaction: discord.Interaction, usuario: discord.Member, carta: str, quantidade: int = 1, origem: str = "bolso"):
    try:
        await interaction.response.defer()
    except discord.errors.NotFound:
        return
    if quantidade < 1:
        await interaction.followup.send("❌ A quantidade deve ser pelo menos 1.")
        return
    if origem not in ("bolso", "caixa"):
        await interaction.followup.send("❌ Origem inválida. Use **bolso** ou **caixa**.")
        return
    removido = await remover_carta_deck(usuario, carta, quantidade, origem)
    if not removido:
        await interaction.followup.send(f"❌ {usuario.mention} não tem **{quantidade}x {carta}** no {origem}.")
        return
    await interaction.followup.send(f"✅ **{quantidade}x {carta}** removida(s) do {origem} de {usuario.mention}.")
 
 
@bot.tree.command(name="cadastrar_imagem", description="[MOD] Definir a imagem do deck de um jogador")
@app_commands.checks.has_permissions(manage_guild=True)
async def cadastrar_imagem(interaction: discord.Interaction, usuario: discord.Member, url: str):
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.errors.NotFound:
        return
    await cadastrar_imagem_usuario(usuario, url)
    await interaction.followup.send(f"✅ Imagem de **{usuario.name}** atualizada.", ephemeral=True)
 
 
bot.run(os.getenv("TOKEN_BOT"))