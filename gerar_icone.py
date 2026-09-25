"""Gera o icone do app: tesoura sobre fundo azul arredondado."""
import os

from PIL import Image, ImageDraw

BASE = os.path.dirname(os.path.abspath(__file__))
MASTER = 1024
ESCALA = 4
LADO = MASTER * ESCALA


def fundo(cor_topo, cor_base):
    imagem = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    for y in range(LADO):
        t = y / (LADO - 1)
        desenho.line(
            [(0, y), (LADO, y)],
            fill=(
                int(cor_topo[0] + (cor_base[0] - cor_topo[0]) * t),
                int(cor_topo[1] + (cor_base[1] - cor_topo[1]) * t),
                int(cor_topo[2] + (cor_base[2] - cor_topo[2]) * t),
                255,
            ),
        )
    return imagem, desenho


def cortar_cantos(imagem, raio):
    mascara = Image.new("L", (LADO, LADO), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, LADO - 1, LADO - 1], radius=raio, fill=255)
    saida = imagem.copy()
    saida.putalpha(mascara)
    return saida


def tesoura(imagem):
    """Desenha duas laminas cruzadas com dois aneis de cabo."""
    u = LADO / 1000.0
    pivo = (500 * u, 430 * u)
    espessura = max(2, int(58 * u))
    branco = (255, 255, 255, 255)
    sombra = (0, 0, 0, 90)

    for dx, dy, cor in ((0.03, 0.03, sombra), (0, 0, branco)):
        camada = Image.new("RGBA", (LADO, LADO), (0, 0, 0, 0))
        desenhar_laminas(ImageDraw.Draw(camada), u, pivo, espessura, cor, (dx * u, dy * u))
        imagem.alpha_composite(camada)
    return imagem


def desenhar_laminas(d, u, pivo, espessura, cor, off):
    topo = (pivo[0] + off[0], pivo[1] + off[1])
    # ponto onde os cabos se unem as laminas
    juncao = (topo[0], topo[1] + 60 * u)
    for sinal in (-1, 1):
        d.line(
            [juncao, (topo[0] + sinal * 210 * u, topo[1] + 400 * u)],
            fill=cor,
            width=espessura,
        )
    # aneis dos cabos
    raio = 105 * u
    for sinal in (-1, 1):
        cx = topo[0] + sinal * 175 * u
        cy = topo[1] - 60 * u
        d.ellipse(
            [cx - raio, cy - raio, cx + raio, cy + raio],
            outline=cor,
            width=int(52 * u),
        )
    # pivo
    d.ellipse(
        [topo[0] - 42 * u, topo[1] - 42 * u, topo[0] + 42 * u, topo[1] + 42 * u],
        fill=cor,
    )


def main():
    imagem, desenho = fundo((37, 118, 255), (15, 34, 88))
    imagem = cortar_cantos(imagem, int(190 * ESCALA))
    imagem = tesoura(imagem)

    os.makedirs(os.path.join(BASE, "assets"), exist_ok=True)
    png = os.path.join(BASE, "assets", "icone.png")
    imagem.resize((512, 512), Image.LANCZOS).save(png)

    ico = os.path.join(BASE, "assets", "icone.ico")
    tamanhos = [256, 128, 64, 48, 32, 24, 16]
    imagem.resize((256, 256), Image.LANCZOS).save(
        ico, format="ICO", sizes=[(t, t) for t in tamanhos]
    )
    print("gerado:", png)
    print("gerado:", ico)


if __name__ == "__main__":
    main()
