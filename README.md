# Recortar Videos

Baixe vídeos inteiros ou **trechos específicos** do YouTube, vários de cada vez, por uma janelinha no Windows.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D4)

---

## Baixar o .exe pronto

1. Vá em **Releases** e baixe `Recortar Videos.exe` (~29 MB, arquivo único).
2. Coloque numa pasta e dê duplo clique.

Não precisa instalar Python nem nada. O `ffmpeg` é o único extra recomendado (veja abaixo).

## Como usar

1. **Cole o link** do YouTube na caixa de texto.
2. Escolha o que fazer:
   - **vídeo inteiro** — marque a caixa *Baixar o video inteiro*;
   - **um trecho** — preencha **De** e **Até** (`1:30`, `90`, `1:02:30`).
3. **Adicionar link**. O vídeo entra na lista.
4. Selecione os itens da lista e use **+ Trecho** para acrescentar vários cortes do mesmo vídeo.
5. Escolha formato (MP4/MP3), qualidade e a pasta de destino (**Abrir pasta** mostra onde vão cair).
6. **BAIXAR TUDO**.

### Atalho útil

Marque **Corte exato** e preencha o mesmo De/Até em vários links: ele baixa uma faixa de tempo
(por keyframes) em vez de cortar na reencode — é muito mais rápido e não perde qualidade.
Com o corte exato ligado, o arquivo já sai pronto.

## Recursos

- vários links de uma vez e vários trechos por vídeo;
- vídeo inteiro, MP3, ou ambos em colunas separadas;
- qualidades: melhor possível, 1080p, 720p, 480p, 360p, 240p, 144p;
- baixa o ffmpeg sozinho na primeira vez, sem precisar instalar nada;
- salvar e carregar listas em `.json` (dá para montar a lista antes e fechar o app);
- cookies do navegador (Chrome, Edge, Firefox, Brave, Opera, Vivaldi) para vídeos que pedem login;
- botão **Parar** que interrompe tudo na hora;
- barra de progresso, log e contagem de tempo por job.

## Requisitos

Nenhum. É só baixar e abrir.

Na primeira vez o app baixa sozinho o **ffmpeg** (o programa que faz o corte e converte para
MP3), umas 110 MB do site oficial [gyan.dev](https://www.gyan.dev/ffmpeg/builds/). Ele fica
salvo numa pasta `ffmpeg\` ao lado do app, então baixa uma vez só. Você pode ver isso na
primeira execução: aparece o botão **Baixar ffmpeg** do lado do status verde/vermelho, e
também aparece sozinho se você clicar em **BAIXAR TUDO** sem ele.

O **Node.js** é opcional, mas recomendado: sem um runtime JavaScript o YouTube esconde parte
dos formatos disponíveis. Se você já tiver (ou instalar em [nodejs.org](https://nodejs.org)),
o app acha sozinho — o rodapé mostra `ffmpeg: OK | JavaScript: node` quando ambos estão prontos.

Se preferir instalar o ffmpeg por conta própria, em vez de deixar o app baixar:

    winget install Gyan.FFmpeg

O app sempre dá preferência ao ffmpeg já instalado no sistema.

## Rodar pelo código

```bash
pip install -r requirements.txt
python recortar_videos.py
```

## Gerar o .exe

```bash
build_exe.bat
```

Sai em `dist\Recortar Videos.exe`, com o ícone e os detalhes de arquivo já embutidos.
O script chama `gerar_icone.py` para gerar `assets\icone.ico` a partir do desenho em código.

Equivale a:

```bash
pyinstaller --onefile --windowed --name "Recortar Videos" --icon assets\icone.ico --version-file assets\versao_win.txt --collect-all yt_dlp recortar_videos.py
```

O `yt-dlp` vai embutido no executável, então para atualizar o app basta recompilar com um
`yt-dlp` mais novo (`pip install -U yt-dlp`).

## Como funciona

O `yt-dlp` cuida de tudo. Para os trechos o app usa o callback `download_ranges` do yt-dlp
(a opção antiga `download_sections` foi removida nas versões atuais), com ffmpeg para cortar
e, no modo exato, `force_keyframes_at_cuts` para pular direto para o keyframe mais próximo
do início do trecho. Vídeo inteiro não usa nada disso: é só um download normal.

## Licença

Sem licença definida: use à vontade, mas sem garantia de nada.
Baixe apenas o que você tem direito de baixar: respeite os termos de uso do YouTube e
os direitos autorais de quem gravou o vídeo.
