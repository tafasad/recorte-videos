import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import yt_dlp
except ImportError:
    sys.exit("yt-dlp nao encontrado. Instale com:  python -m pip install -U yt-dlp")

try:
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
except Exception:  # noqa: BLE001
    APP_DIR = os.getcwd()

CONFIG_PATH = os.path.join(APP_DIR, "recortar_videos_config.json")

NAVEGADORES = ["desativado", "chrome", "edge", "firefox", "brave", "opera", "vivaldi"]
QUALIDADES = {
    "melhor possivel": "bv*[vcodec!=none][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*[vcodec!=none]+ba/b",
    "1080p": "bv*[height<=1080][vcodec!=none][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080][vcodec!=none]+ba/b[height<=1080]",
    "720p": "bv*[height<=720][vcodec!=none][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/bv*[height<=720][vcodec!=none]+ba/b[height<=720]",
    "480p": "bv*[height<=480][vcodec!=none][ext=mp4]+ba[ext=m4a]/b[height<=480][ext=mp4]/bv*[height<=480][vcodec!=none]+ba/b[height<=480]",
    "360p": "bv*[height<=360][vcodec!=none][ext=mp4]+ba[ext=m4a]/b[height<=360][ext=mp4]/bv*[height<=360][vcodec!=none]+ba/b[height<=360]",
}
FINAL_INFINITO = 24 * 3600
NOME_STATUS = {
    "pendente": "Pendente",
    "trabalhando": "Baixando",
    "ok": "OK",
    "erro": "ERRO",
    "cancelado": "Cancelado",
}


class Cancelled(Exception):
    pass


def parse_tempo(texto):
    texto = (texto or "").strip().replace(",", ".")
    if not texto:
        raise ValueError("Tempo vazio")
    m = re.match(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$", texto, re.I)
    if m and any(m.groups()):
        h, mi, s = int(m.group(1) or 0), int(m.group(2) or 0), float(m.group(3) or 0)
        if mi > 59:
            raise ValueError("Minutos devem ser menores que 60")
        if s > 59.999:
            raise ValueError("Segundos devem ser menores que 60")
        return h * 3600 + mi * 60 + s
    partes = texto.split(":")
    if len(partes) > 3:
        raise ValueError("Formato invalido. Use 90, 1:30 ou 1:02:03")
    total = 0.0
    for parte in partes:
        if not re.match(r"^\d+(\.\d+)?$", parte.strip()):
            raise ValueError("Formato invalido. Use 90, 1:30 ou 1:02:03")
        total = total * 60 + float(parte)
    return total


def fmt_relogio(segundos):
    segundos = max(0.0, float(segundos or 0))
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    s = segundos - h * 3600 - m * 60
    if h:
        return "%d:%02d:%04.1f" % (h, m, s)
    if m:
        return "%d:%04.1f" % (m, s)
    return "%.1fs" % s


def fmt_selo(segundos):
    total = int(round(max(0.0, float(segundos or 0))))
    h, resto = divmod(total, 3600)
    m, s = divmod(resto, 60)
    if h:
        return "%dh%02dm%02ds" % (h, m, s)
    if m:
        return "%dm%02ds" % (m, s)
    return "%ds" % s


def fmt_tamanho(valor):
    numero = float(valor or 0)
    for unidade in ("B", "KB", "MB", "GB"):
        if numero < 1024 or unidade == "GB":
            return "%.0f %s" % (numero, unidade) if unidade == "B" else "%.1f %s" % (numero, unidade)
        numero /= 1024
    return "%.1f GB" % numero


def achatar_url(texto):
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("Cole um link do YouTube")
    if re.match(r"^\d+$", texto) and len(texto) >= 11:
        return "https://www.youtube.com/watch?v=" + texto
    if re.match(r"^youtu\.?be/", texto, re.I):
        return "https://" + texto
    if not re.match(r"^https?://", texto, re.I):
        texto = "https://" + texto
    return texto


def _varrer_rafal(raiz, profundidade=3):
    if not raiz or not os.path.isdir(raiz):
        return None
    pilha = [(raiz, 0)]
    while pilha:
        atual, nivel = pilha.pop()
        if nivel >= profundidade:
            continue
        try:
            entradas = list(os.scandir(atual))
        except OSError:
            continue
        for entrada in entradas:
            if not entrada.is_dir(follow_symlinks=False):
                continue
            for candidato in (
                os.path.join(entrada.path, "ffmpeg.exe"),
                os.path.join(entrada.path, "bin", "ffmpeg.exe"),
            ):
                if os.path.isfile(candidato):
                    return os.path.dirname(candidato)
            pilha.append((entrada.path, nivel + 1))
    return None


def achar_ffmpeg():
    executavel = shutil.which("ffmpeg")
    if executavel:
        return os.path.dirname(executavel)
    local = os.environ.get("LOCALAPPDATA", "")
    for raiz in (
        os.path.join(local, "Microsoft", "WinGet", "Packages"),
        r"C:\ffmpeg",
        r"C:\Program Files\ffmpeg",
    ):
        achado = _varrer_rafal(raiz)
        if achado:
            return achado
    return None


def achar_js_runtime():
    """
    O yt-dlp precisa de um runtime JavaScript para extrair todos os formatos do YouTube.
    """
    for nome, executavel in (("deno", "deno"), ("node", "node"), ("bun", "bun"), ("quickjs", "quickjs")):
        caminho = shutil.which(executavel)
        if caminho:
            return nome, caminho
    return None, None


def ativar_ffmpeg():
    """
    O YoutubeFD.available() do yt-dlp ignora o parametro ffmpeg_location quando a API
    Python e usada, entao o diretorio precisa estar no PATH do processo.
    """
    diretorio = achar_ffmpeg()
    if not diretorio:
        return None
    partes = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if diretorio.lower() not in [p.lower() for p in partes]:
        os.environ["PATH"] = os.pathsep.join([diretorio] + partes)
    return diretorio


class Logger:
    def __init__(self, destino):
        self.destino = destino

    def debug(self, msg):
        if not msg.startswith("[debug] "):
            self.destino(msg)

    def info(self, msg):
        self.destino(msg)

    def warning(self, msg):
        self.destino("AVISO: " + msg)

    def error(self, msg):
        self.destino("ERRO: " + msg)


def montar_ranges(job):
    def download_ranges(info_dict, _ydl):
        duracao = info_dict.get("duration")
        fim = job["fim"] if job["fim"] is not None else duracao
        return [
            {
                "start_time": float(job["inicio"]),
                "end_time": float(fim) if fim is not None else float("inf"),
                "title": None,
                "index": 1,
            }
        ]

    return download_ranges


def montar_opcoes(job, config, ffmpeg_dir, gancho_progresso, gancho_pos, destino_log):
    inteiro = bool(job.get("inteiro"))
    if inteiro:
        nome_saida = "%(title).80B [%(id)s].%(ext)s"
    else:
        selo = fmt_selo(job["inicio"])
        selo += "-" + fmt_selo(job["fim"]) if job["fim"] is not None else "-fim"
        nome_saida = "%(title).70B [%(id)s] - " + selo + ".%(ext)s"

    opcoes = {
        "format": "bestaudio/best"
        if config["formato"] == "mp3"
        else QUALIDADES[config["qualidade"]],
        "outtmpl": os.path.join(config["pasta"], nome_saida),
        "noplaylist": True,
        "retries": 5,
        "fragment_retries": 5,
        "continuedl": True,
        "overwrites": True,
        "noprogress": True,
        "logger": Logger(destino_log),
        "progress_hooks": [gancho_progresso],
        "postprocessor_hooks": [gancho_pos],
        "merge_output_format": "mp4",
    }
    if not inteiro:
        opcoes["download_ranges"] = montar_ranges(job)
        opcoes["force_keyframes_at_cuts"] = bool(config.get("corte_exato", True))
    if ffmpeg_dir:
        opcoes["ffmpeg_location"] = ffmpeg_dir
    if config["formato"] == "mp3":
        opcoes["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(config["qualidade_audio"]),
            }
        ]
    navegador = config.get("navegador", "desativado")
    if navegador and navegador != "desativado":
        opcoes["cookiesfrombrowser"] = (navegador,)
    nome_js, caminho_js = achar_js_runtime()
    if nome_js:
        opcoes["js_runtimes"] = {nome_js: {"path": caminho_js}}
    return opcoes


def baixar_jobs(jobs, config, ffmpeg_dir, parar, emitir):
    total = len(jobs)
    contagem = {"ok": 0, "erro": 0, "cancelado": 0}

    for indice, job in enumerate(jobs):
        if parar.is_set():
            break
        iid = job["iid"]
        if job.get("inteiro"):
            rotulo = "%s | video inteiro" % job["titulo"][:38]
        else:
            rotulo = "%s | %s-%s" % (
                job["titulo"][:38],
                fmt_relogio(job["inicio"]),
                fmt_relogio(job["fim"]) if job["fim"] is not None else "fim",
            )
        estado = {"texto": rotulo, "marcado": 0.0, "ultimo": 0.0}

        def barra(fracao):
            emitir("barra", ((indice + max(0.0, min(1.0, fracao))) / total, estado))

        def progresso(dados):
            if parar.is_set():
                raise Cancelled()
            total_bytes = dados.get("total_bytes") or dados.get("total_bytes_estimate") or 0
            baixados = dados.get("downloaded_bytes") or 0
            fracao = 1.0 if dados.get("status") == "finished" else (min(1.0, baixados / total_bytes) if total_bytes else 0.0)
            agora = time.monotonic()
            estado["marcado"] = fracao
            barra(fracao)
            if agora - estado["ultimo"] < 0.25 and fracao < 1.0:
                return
            estado["ultimo"] = agora
            emitir(
                "linha",
                (
                    iid,
                    "trabalhando",
                    "%.1f MB / %.1f MB" % (baixados / 1048576.0, total_bytes / 1048576.0) if total_bytes else "baixando",
                ),
            )

        def posproc(dados):
            if parar.is_set():
                raise Cancelled()
            if dados.get("status") == "started":
                estado["texto"] = rotulo + " (cortando com ffmpeg)"
                emitir("linha", (iid, "trabalhando", "cortando com ffmpeg..."))

        opcoes = montar_opcoes(job, config, ffmpeg_dir, progresso, posproc, lambda m: emitir("log", m))
        emitir("linha", (iid, "trabalhando", "iniciando..."))
        estado["texto"] = rotulo
        barra(0.0)
        try:
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                ydl.download([job["url"]])
            contagem["ok"] += 1
            emitir("linha", (iid, "ok", job.get("detalhe") or ""))
        except Cancelled:
            contagem["cancelado"] += 1
            emitir("linha", (iid, "cancelado", ""))
            break
        except Exception as exc:  # noqa: BLE001
            contagem["erro"] += 1
            mensagem = str(exc).replace("\n", " ").strip() or exc.__class__.__name__
            emitir("linha", (iid, "erro", mensagem[:200]))
            emitir("log", "ERRO em %s -> %s" % (rotulo, mensagem))
        barra(1.0)

    emitir("barra", (1.0, {"texto": "Concluido", "marcado": 1.0}))
    emitir("fim", contagem)


def carregar_config():
    padrao = {
        "pasta": os.path.join(APP_DIR, "recortes"),
        "formato": "mp4",
        "qualidade": "melhor possivel",
        "qualidade_audio": 192,
        "navegador": "desativado",
        "playlists": False,
        "corte_exato": True,
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        if isinstance(dados, dict):
            padrao.update({k: v for k, v in dados.items() if k in padrao})
    except (OSError, ValueError):
        pass
    padrao["pasta"] = os.path.abspath(os.path.expanduser(str(padrao["pasta"])))
    return padrao


def salvar_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as arquivo:
            json.dump(config, arquivo, indent=2, ensure_ascii=False)
    except OSError:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Recortar videos do YouTube")
        self.geometry("1040x720")
        self.minsize(920, 620)

        self.config = carregar_config()
        self.jobs = []
        self.eventos = queue.Queue()
        self.parar_event = threading.Event()
        self.thread = None
        self.seq = 0

        self.var_url = tk.StringVar()
        self.var_inicio = tk.StringVar(value="0:00")
        self.var_fim = tk.StringVar()
        self.var_pasta = tk.StringVar(value=self.config["pasta"])
        self.var_formato = tk.StringVar(value=self.config["formato"])
        self.var_qualidade = tk.StringVar(value=self.config["qualidade"])
        self.var_audio = tk.StringVar(value=str(self.config["qualidade_audio"]))
        self.var_navegador = tk.StringVar(value=self.config["navegador"])
        self.var_playlists = tk.BooleanVar(value=self.config["playlists"])
        self.var_corte_exato = tk.BooleanVar(value=self.config["corte_exato"])
        self.var_inteiro = tk.BooleanVar(value=False)
        self.var_status = tk.StringVar(value="Pronto. Cole um link do YouTube e clique em Adicionar link.")
        self.var_ffmpeg = tk.StringVar()
        self.var_dica = tk.StringVar()

        estilo = ttk.Style(self)
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")

        self.montar_widgets()
        self.alternar_campos()
        self.after(120, self.processar_eventos)

    def montar_widgets(self):
        moldura = ttk.Frame(self, padding=10)
        moldura.pack(fill="both", expand=True)
        moldura.columnconfigure(0, weight=1)
        moldura.rowconfigure(3, weight=1)

        moldura_link = ttk.LabelFrame(moldura, text="1. Link", padding=8)
        moldura_link.grid(row=0, column=0, sticky="ew")
        moldura_link.columnconfigure(1, weight=1)
        self.entrada_url = ttk.Entry(moldura_link, textvariable=self.var_url)
        self.entrada_url.grid(row=0, column=1, sticky="ew", padx=6)
        self.entrada_url.bind("<Return>", lambda _e: self.adicionar_link())
        self.btn_link = ttk.Button(moldura_link, text="Adicionar link", command=self.adicionar_link)
        self.btn_link.grid(row=0, column=2)
        self.check_playlists = ttk.Checkbutton(
            moldura_link, text="Incluir playlists inteiras", variable=self.var_playlists
        )
        self.check_playlists.grid(row=1, column=1, sticky="w", padx=6, pady=(6, 0))
        self.check_inteiro = ttk.Checkbutton(
            moldura_link, text="Baixar o video inteiro", variable=self.var_inteiro, command=self.alternar_campos
        )
        self.check_inteiro.grid(row=1, column=2, sticky="w", padx=(0, 14), pady=(6, 0))

        moldura_trecho = ttk.LabelFrame(moldura, text="2. Trecho (vale para os itens selecionados)", padding=8)
        moldura_trecho.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(moldura_trecho, text="De:").grid(row=0, column=0)
        self.entrada_inicio = ttk.Entry(moldura_trecho, textvariable=self.var_inicio, width=11)
        self.entrada_inicio.grid(row=0, column=1, padx=(4, 12))
        ttk.Label(moldura_trecho, text="Ate:").grid(row=0, column=2)
        self.entrada_fim = ttk.Entry(moldura_trecho, textvariable=self.var_fim, width=11)
        self.entrada_fim.grid(row=0, column=3, padx=(4, 12))
        self.entrada_fim.bind("<Return>", lambda _e: self.adicionar_trecho())
        self.entrada_inicio.bind("<Return>", lambda _e: self.adicionar_trecho())
        self.btn_trecho = ttk.Button(moldura_trecho, text="Adicionar trecho", command=self.adicionar_trecho)
        self.btn_trecho.grid(row=0, column=4)
        ttk.Label(
            moldura_trecho,
            text="Aceita 90 | 1:30 | 1:02:03 | 1h2m3s   (Ate vazio = ate o fim)",
            foreground="#555555",
        ).grid(row=0, column=5, sticky="w", padx=(12, 0))

        barra_acoes = ttk.Frame(moldura)
        barra_acoes.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.btn_baixar = ttk.Button(barra_acoes, text="BAIXAR TUDO", command=self.iniciar_download)
        self.btn_baixar.pack(side="left")
        self.btn_parar = ttk.Button(barra_acoes, text="Parar", command=self.parar_download, state="disabled")
        self.btn_parar.pack(side="left", padx=6)
        self.btn_remover = ttk.Button(barra_acoes, text="Remover", command=self.remover)
        self.btn_remover.pack(side="left")
        self.btn_limpar_ok = ttk.Button(barra_acoes, text="Limpar concluidos", command=self.limpar_concluidos)
        self.btn_limpar_ok.pack(side="left", padx=6)
        self.btn_limpar = ttk.Button(barra_acoes, text="Limpar lista", command=self.limpar_lista)
        self.btn_limpar.pack(side="left")
        self.btn_salvar = ttk.Button(barra_acoes, text="Salvar lista", command=self.exportar_lista)
        self.btn_salvar.pack(side="left", padx=6)
        self.btn_carregar = ttk.Button(barra_acoes, text="Carregar lista", command=self.importar_lista)
        self.btn_carregar.pack(side="left")
        ttk.Button(barra_acoes, text="Abrir pasta", command=self.abrir_pasta).pack(side="right")

        moldura_lista = ttk.Frame(moldura)
        moldura_lista.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        moldura_lista.rowconfigure(0, weight=1)
        moldura_lista.columnconfigure(0, weight=1)
        colunas = ("n", "video", "trecho", "status", "detalhe")
        self.arvore = ttk.Treeview(moldura_lista, columns=colunas, show="headings", selectmode="extended")
        for chave, titulo, largura, centro, estica in (
            ("n", "#", 42, True, False),
            ("video", "Video", 360, False, True),
            ("trecho", "Trecho", 150, True, False),
            ("status", "Status", 100, True, False),
            ("detalhe", "Detalhe", 210, False, True),
        ):
            self.arvore.heading(chave, text=titulo)
            self.arvore.column(chave, width=largura, anchor="center" if centro else "w", stretch=estica)
        self.arvore.grid(row=0, column=0, sticky="nsew")
        rolagem = ttk.Scrollbar(moldura_lista, orient="vertical", command=self.arvore.yview)
        rolagem.grid(row=0, column=1, sticky="ns")
        self.arvore.configure(yscrollcommand=rolagem.set)
        for tag, cor in (("erro", "#b00020"), ("ok", "#1b6b2a"), ("trabalhando", "#0b5cad"), ("cancelado", "#8a6d00")):
            self.arvore.tag_configure(tag, foreground=cor)

        moldura_opcoes = ttk.LabelFrame(moldura, text="Opcoes", padding=8)
        moldura_opcoes.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(moldura_opcoes, text="Pasta:").grid(row=0, column=0)
        self.entrada_pasta = ttk.Entry(moldura_opcoes, textvariable=self.var_pasta, width=40)
        self.entrada_pasta.grid(row=0, column=1, padx=6)
        ttk.Button(moldura_opcoes, text="Escolher...", command=self.escolher_pasta).grid(row=0, column=2)
        ttk.Label(moldura_opcoes, text="Formato:").grid(row=0, column=3, padx=(18, 0))
        self.cb_formato = ttk.Combobox(
            moldura_opcoes, textvariable=self.var_formato, values=["mp4", "mp3"], width=6, state="readonly"
        )
        self.cb_formato.grid(row=0, column=4, padx=6)
        self.cb_formato.bind("<<ComboboxSelected>>", lambda _e: self.alternar_campos())
        ttk.Label(moldura_opcoes, text="Video:").grid(row=0, column=5, padx=(18, 0))
        self.cb_qualidade = ttk.Combobox(
            moldura_opcoes, textvariable=self.var_qualidade, values=list(QUALIDADES), width=15, state="readonly"
        )
        self.cb_qualidade.grid(row=0, column=6, padx=6)
        ttk.Label(moldura_opcoes, text="Audio:").grid(row=1, column=0, pady=(6, 0))
        self.cb_audio = ttk.Combobox(
            moldura_opcoes, textvariable=self.var_audio, values=["320", "256", "192", "128", "96"], width=6, state="readonly"
        )
        self.cb_audio.grid(row=1, column=1, padx=6, pady=(6, 0), sticky="w")
        ttk.Label(moldura_opcoes, text="Cookies:").grid(row=1, column=2, padx=(18, 0), pady=(6, 0))
        self.cb_navegador = ttk.Combobox(
            moldura_opcoes, textvariable=self.var_navegador, values=NAVEGADORES, width=11, state="readonly"
        )
        self.cb_navegador.grid(row=1, column=3, padx=6, pady=(6, 0))
        self.var_dica.set(
            "Corte exato re-codifica o trecho (corte no frame exato, mais lento). "
            "Desmarque para copiar o stream e ganhar velocidade, com corte aproximado. "
            "Cookies: escolha o navegador e feche-o antes de baixar (videos com login ou restricao de idade)."
        )
        self.check_corte = ttk.Checkbutton(
            moldura_link, text="Corte exato (re-codifica)", variable=self.var_corte_exato
        )
        self.check_corte.grid(row=1, column=2, sticky="w", padx=(0, 14), pady=(6, 0))
        ttk.Label(moldura_opcoes, textvariable=self.var_dica, foreground="#555555", wraplength=880).grid(
            row=2, column=0, columnspan=7, sticky="w", pady=(6, 0)
        )
        ffmpeg_dir = ativar_ffmpeg()
        nome_js, caminho_js = achar_js_runtime()
        self.var_ffmpeg.set(
            "ffmpeg: %s   |   JavaScript: %s"
            % ("OK" if ffmpeg_dir else "NAO ENCONTRADO", nome_js or "NAO ENCONTRADO (instale Node ou Deno)")
        )
        ttk.Label(moldura_opcoes, textvariable=self.var_ffmpeg, foreground=("#1b6b2a" if ffmpeg_dir else "#b00020")).grid(
            row=3, column=0, columnspan=7, sticky="w", pady=(6, 0)
        )

        rodape = ttk.Frame(moldura)
        rodape.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.barra = ttk.Progressbar(rodape, mode="determinate", maximum=1.0)
        self.barra.pack(side="left", fill="x", expand=True)
        ttk.Label(rodape, textvariable=self.var_status, anchor="e").pack(side="right", padx=(10, 0))

        self.log = tk.Text(
            moldura, height=8, wrap="word", state="disabled", background="#101418", foreground="#d5dde5", relief="flat"
        )
        self.log.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(moldura, text="Limpar log", command=self.limpar_log).grid(row=7, column=0, sticky="e", pady=(4, 0))

        self.logar("ffmpeg: %s" % (ffmpeg_dir or "nao encontrado no PATH"))
        self.logar("JavaScript runtime: %s (%s)" % (nome_js or "nenhum", caminho_js or "instale Node ou Deno"))

        self.bind("<Delete>", lambda _e: self.remover())

    def alternar_campos(self):
        mp3 = self.var_formato.get() == "mp3"
        self.cb_qualidade.configure(state="disabled" if mp3 else "readonly")
        self.cb_audio.configure(state="readonly" if mp3 else "disabled")
        inteiro = self.var_inteiro.get()
        estado_trecho = "disabled" if inteiro else "normal"
        for widget in (self.entrada_inicio, self.entrada_fim, self.btn_trecho, self.check_corte):
            widget.configure(state=estado_trecho)

    def logar(self, texto):
        if not texto:
            return
        self.log.configure(state="normal")
        self.log.insert("end", texto.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def limpar_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def ocupado(self):
        return bool(self.thread and self.thread.is_alive())

    def criar_job(self, video, inicio, fim, inteiro=False):
        duracao = video.get("duration")
        if not inteiro:
            if duracao and duracao > 0:
                inicio = max(0.0, min(inicio, max(0.0, duracao - 0.5)))
                if fim is not None:
                    fim = min(fim, duracao)
            if fim is not None and fim - inicio < 0.5:
                return None
        if any(
            j["url"] == video["url"]
            and bool(j.get("inteiro")) == inteiro
            and (inteiro or (abs(j["inicio"] - inicio) < 0.5 and j["fim"] == fim))
            for j in self.jobs
        ):
            return None
        self.seq += 1
        job = {
            "iid": "j%d" % self.seq,
            "url": video["url"],
            "titulo": video.get("titulo") or video["url"],
            "duracao": duracao,
            "inteiro": inteiro,
            "inicio": None if inteiro else round(inicio, 3),
            "fim": None if inteiro or fim is None else round(fim, 3),
            "status": "pendente",
            "detalhe": "video de %s" % fmt_relogio(duracao) if duracao else "",
        }
        self.jobs.append(job)
        if inteiro:
            trecho = "inteiro"
        else:
            trecho = "%s - %s" % (
                fmt_relogio(job["inicio"]),
                fmt_relogio(job["fim"]) if job["fim"] is not None else "fim",
            )
        self.arvore.insert(
            "",
            "end",
            iid=job["iid"],
            values=(len(self.jobs), job["titulo"], trecho, NOME_STATUS["pendente"], job["detalhe"]),
        )
        return job

    def adicionar_links(self, videos, inicio, fim, inteiro=False):
        adicionados = ignorados = 0
        for video in videos:
            if self.criar_job(video, inicio, fim, inteiro):
                adicionados += 1
            else:
                ignorados += 1
        return adicionados, ignorados

    def adicionar_link(self):
        if self.ocupado():
            return
        try:
            url = achatar_url(self.var_url.get())
        except ValueError as exc:
            messagebox.showwarning("Link", str(exc))
            return
        self.var_url.set(url)
        self.var_status.set("Consultando o link...")
        self.logar("Consultando %s" % url)
        config = self.coletar_config()
        ffmpeg_dir = ativar_ffmpeg()

        def worker():
            opcoes = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": not config["playlists"],
                "logger": Logger(lambda m: self.eventos.put(("log", m))),
            }
            if ffmpeg_dir:
                opcoes["ffmpeg_location"] = ffmpeg_dir
            nome_js, caminho_js = achar_js_runtime()
            if nome_js:
                opcoes["js_runtimes"] = {nome_js: {"path": caminho_js}}
            try:
                with yt_dlp.YoutubeDL(opcoes) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as exc:  # noqa: BLE001
                self.eventos.put(("consulta_erro", str(exc).replace("\n", " ") or exc.__class__.__name__))
                return
            if not info:
                self.eventos.put(("consulta_erro", "O link nao retornou informacoes"))
                return
            itens = info.get("entries") or [info]
            itens = [i for i in itens if i]
            videos = [
                {
                    "url": item.get("webpage_url") or item.get("original_url") or item.get("url") or url,
                    "titulo": item.get("title") or "sem titulo",
                    "duration": item.get("duration"),
                }
                for item in itens
            ]
            self.eventos.put(("consulta_ok", videos))

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def consulta_concluida(self, videos):
        inteiro = self.var_inteiro.get()
        inicio, fim = 0.0, None
        if not inteiro:
            try:
                inicio = parse_tempo(self.var_inicio.get())
            except ValueError as exc:
                messagebox.showwarning("Tempo", str(exc))
                return
            texto_fim = self.var_fim.get().strip()
            if texto_fim:
                try:
                    fim = parse_tempo(texto_fim)
                except ValueError as exc:
                    messagebox.showwarning("Tempo", str(exc))
                    return
                if fim <= inicio:
                    messagebox.showwarning("Tempo", "'Ate' precisa ser maior que 'De'")
                    return
        adicionados, ignorados = self.adicionar_links(videos, inicio, fim, inteiro)
        self.var_url.set("")
        texto = "%d item(ns) criado(s) | %d na lista" % (adicionados, len(self.jobs))
        if ignorados:
            texto += " | %d ignorado(s)" % ignorados
        self.var_status.set(texto + ".")
        self.logar(texto)

    def adicionar_trecho(self):
        if self.ocupado() or self.var_inteiro.get():
            return
        try:
            inicio = parse_tempo(self.var_inicio.get())
            texto_fim = self.var_fim.get().strip()
            fim = parse_tempo(texto_fim) if texto_fim else None
        except ValueError as exc:
            messagebox.showwarning("Tempo", "%s\n\nExemplos: 1:30 | 90 | 1:02:03 | 1h2m3s" % exc)
            return
        if fim is not None and fim <= inicio:
            messagebox.showwarning("Tempo", "'Ate' precisa ser maior que 'De'")
            return
        selecionados = [iid for iid in self.arvore.selection()]
        if not selecionados:
            messagebox.showinfo("Selecao", "Selecione um ou mais videos na lista antes de adicionar o trecho.")
            return
        alvos = [j for j in self.jobs if j["iid"] in selecionados and j["status"] == "pendente"]
        if not alvos:
            messagebox.showinfo("Selecao", "Os itens selecionados nao estao pendentes.")
            return
        adicionados, ignorados = self.adicionar_links(
            [{"url": j["url"], "titulo": j["titulo"], "duration": j["duracao"]} for j in alvos], inicio, fim
        )
        self.var_fim.set("")
        texto = "%d recorte(s) adicionado(s) para %d video(s)" % (adicionados, len(alvos))
        if ignorados:
            texto += " | %d ignorado(s) (duplicado ou fora de duracao)" % ignorados
        self.var_status.set(texto + ".")
        self.logar(texto)

    def remover(self):
        if self.ocupado():
            return
        selecao = list(self.arvore.selection())
        if not selecao:
            return
        for iid in selecao:
            self.arvore.delete(iid)
        self.jobs = [j for j in self.jobs if j["iid"] not in selecao]
        self.renumerar()

    def limpar_concluidos(self):
        if self.ocupado():
            return
        alvos = [j["iid"] for j in self.jobs if j["status"] in ("ok", "erro", "cancelado")]
        for iid in alvos:
            self.arvore.delete(iid)
        self.jobs = [j for j in self.jobs if j["iid"] not in alvos]
        self.renumerar()
        self.var_status.set("Removidos %d item(ns)." % len(alvos))

    def limpar_lista(self):
        if self.ocupado():
            return
        if self.jobs and not messagebox.askyesno("Limpar lista", "Apagar os %d itens?" % len(self.jobs)):
            return
        for job in self.jobs:
            self.arvore.delete(job["iid"])
        self.jobs = []
        self.barra["value"] = 0
        self.var_status.set("Lista vazia.")

    def renumerar(self):
        for posicao, job in enumerate(self.jobs, 1):
            if self.arvore.exists(job["iid"]):
                self.arvore.set(job["iid"], "n", posicao)

    def coletar_config(self):
        pasta = self.var_pasta.get().strip() or os.path.join(APP_DIR, "recortes")
        self.config["pasta"] = os.path.abspath(os.path.expanduser(pasta))
        self.config["formato"] = self.var_formato.get()
        self.config["qualidade"] = self.var_qualidade.get()
        try:
            self.config["qualidade_audio"] = int(self.var_audio.get())
        except ValueError:
            self.config["qualidade_audio"] = 192
        self.config["navegador"] = self.var_navegador.get()
        self.config["playlists"] = self.var_playlists.get()
        self.config["corte_exato"] = self.var_corte_exato.get()
        salvar_config(self.config)
        return self.config

    def escolher_pasta(self):
        pasta = filedialog.askdirectory(initialdir=self.var_pasta.get() or APP_DIR)
        if pasta:
            self.var_pasta.set(pasta)
            self.coletar_config()

    def abrir_pasta(self):
        pasta = self.var_pasta.get().strip() or os.path.join(APP_DIR, "recortes")
        os.makedirs(pasta, exist_ok=True)
        os.startfile(pasta)

    def exportar_lista(self):
        destino = filedialog.asksaveasfilename(
            defaultextension=".json", initialfile="recortes.json", filetypes=[("Lista de recortes", "*.json")]
        )
        if not destino:
            return
        dados = [
            {
                "url": j["url"],
                "titulo": j["titulo"],
                "duracao": j["duracao"],
                "inteiro": bool(j.get("inteiro")),
                "inicio": j["inicio"],
                "fim": j["fim"],
            }
            for j in self.jobs
        ]
        try:
            with open(destino, "w", encoding="utf-8") as arquivo:
                json.dump(dados, arquivo, indent=2, ensure_ascii=False)
            self.var_status.set("Lista salva em %s" % destino)
        except OSError as exc:
            messagebox.showerror("Salvar lista", str(exc))

    def importar_lista(self):
        origem = filedialog.askopenfilename(filetypes=[("Lista de recortes", "*.json")])
        if not origem:
            return
        try:
            with open(origem, "r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)
            if not isinstance(dados, list):
                raise ValueError("O arquivo nao contem uma lista de recortes")
            adicionados = ignorados = 0
            for item in dados:
                if not isinstance(item, dict) or not item.get("url"):
                    ignorados += 1
                    continue
                video = {
                    "url": item["url"],
                    "titulo": item.get("titulo", item["url"]),
                    "duration": item.get("duracao"),
                }
                inteiro = bool(item.get("inteiro"))
                inicio = 0.0 if inteiro else float(item.get("inicio") or 0)
                if self.criar_job(video, inicio, item.get("fim"), inteiro):
                    adicionados += 1
                else:
                    ignorados += 1
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Carregar lista", str(exc))
            return
        texto = "Lista carregada: %d item(ns)" % adicionados
        if ignorados:
            texto += " | %d ignorado(s)" % ignorados
        self.var_status.set(texto + ".")
        self.logar(texto)

    def iniciar_download(self):
        if self.ocupado():
            return
        ffmpeg_dir = ativar_ffmpeg()
        if not ffmpeg_dir:
            messagebox.showerror("ffmpeg", "ffmpeg nao encontrado.\n\nInstale com:  winget install Gyan.FFmpeg")
            return
        pendentes = [j for j in self.jobs if j["status"] in ("pendente", "erro")]
        if not pendentes:
            messagebox.showinfo("Nada para baixar", "Nao ha recorte pendente na lista.")
            return
        config = self.coletar_config()
        try:
            os.makedirs(config["pasta"], exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Pasta de destino", str(exc))
            return
        for job in pendentes:
            job["status"] = "pendente"
            job["detalhe"] = "na fila"
            self.atualizar_linha(job["iid"], "pendente", "na fila")
        self.parar_event.clear()
        self.barra["value"] = 0
        self.travas(True)
        self.logar("Baixando %d recorte(s) para %s" % (len(pendentes), config["pasta"]))

        def worker():
            baixar_jobs(
                pendentes, config, ffmpeg_dir, self.parar_event, lambda tipo, dado: self.eventos.put((tipo, dado))
            )

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def parar_download(self):
        self.parar_event.set()
        self.var_status.set("Parando no proximo passo...")
        self.btn_parar.configure(state="disabled")

    def travas(self, bloqueio):
        for botao in (self.btn_link, self.btn_trecho, self.btn_remover, self.btn_limpar_ok, self.btn_limpar, self.btn_salvar, self.btn_carregar):
            botao.configure(state="disabled" if bloqueio else "normal")
        self.btn_baixar.configure(state="disabled" if bloqueio else "normal")
        self.btn_parar.configure(state="normal" if bloqueio else "disabled")
        for widget in (self.entrada_url, self.entrada_inicio, self.entrada_fim, self.entrada_pasta, self.check_playlists, self.check_corte, self.check_inteiro, self.cb_formato, self.cb_navegador):
            widget.configure(state="disabled" if bloqueio else "normal")
        if not bloqueio:
            self.alternar_campos()

    def atualizar_linha(self, iid, status=None, detalhe=None):
        job = next((j for j in self.jobs if j["iid"] == iid), None)
        if not job or not self.arvore.exists(iid):
            return
        if status is not None:
            job["status"] = status
        if detalhe is not None:
            job["detalhe"] = detalhe
        valores = list(self.arvore.item(iid, "values"))
        valores[3] = NOME_STATUS.get(job["status"], job["status"])
        valores[4] = (job["detalhe"] or "")[:200]
        self.arvore.item(iid, values=valores, tags=(job["status"],))
        self.arvore.see(iid)

    def processar_eventos(self):
        try:
            while True:
                tipo, dado = self.eventos.get_nowait()
                if tipo == "log":
                    self.logar(dado)
                elif tipo == "linha":
                    self.atualizar_linha(*dado)
                elif tipo == "barra":
                    fracao, estado = dado
                    self.barra["value"] = max(0.0, min(1.0, fracao))
                    self.var_status.set(estado.get("texto", ""))
                elif tipo == "consulta_ok":
                    self.consulta_concluida(dado)
                elif tipo == "consulta_erro":
                    self.var_status.set("Falha ao consultar o link.")
                    self.logar("ERRO: " + dado)
                    messagebox.showerror("Link", dado[:500])
                elif tipo == "fim":
                    self.travas(False)
                    self.barra["value"] = 1.0
                    extras = ", cancelado" if dado["cancelado"] else ""
                    texto = "Concluido: %d ok, %d erro(s)%s" % (dado["ok"], dado["erro"], extras)
                    self.var_status.set(texto + ".")
                    self.logar(texto)
        except queue.Empty:
            pass
        self.after(120, self.processar_eventos)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
