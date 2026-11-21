"""Anel RFID/NFC para maquiagem acessivel - VERSAO 2 (conectada a internet).

Diferenca em relacao a V1 (anel_rfid_v1.py): em vez de uma lista fixa de
3 produtos dentro do codigo, esta versao conecta o ESP32 ao WiFi e busca
os dados dos produtos (nome/cor/marca/audio) em uma pagina publicada no
GitHub Pages (ver pasta github_pages/ deste projeto). O arquivo de audio
de cada produto tambem e baixado dessa pagina na primeira vez que a tag
correspondente e lida, e fica guardado em cache na flash do ESP32 (assim
nas proximas leituras ele toca na hora, sem precisar da rede).

Hardware: igual a V1 -- NFC via PN532 (fiacao autodetectada) e audio via
codec ES8311 (ver cabecalho/comentarios de anel_rfid_v1.py para detalhes
de pinagem; aqui so repetimos o necessario).

Pre-requisitos no dispositivo (viper-ide.org):
  1. Copie para o ESP32: pn532.py, anel_rfid_v2.py e a biblioteca
     urequests.py (se o seu firmware MicroPython nao tiver "urequests"
     embutido -- baixe de https://github.com/micropython/micropython-lib
     o arquivo "urequests/urequests.py" e salve na flash com esse nome).
  2. Publique a pagina de produtos seguindo github_pages/README.md e
     cadastre ao menos 1 produto pelo painel em /admin/.
  3. Ajuste WIFI_SSID, WIFI_SENHA e BASE_URL abaixo.
  4. Rode anel_rfid_v2.py. No primeiro boot ele conecta ao WiFi, baixa
     produtos.json e fica pronto para ler tags; o audio de cada produto
     e baixado so quando a tag dele e lida por aproximacao pela primeira
     vez (depois fica em cache em /audio_cache/).

Se a rede WiFi nao estiver disponivel no momento, o anel continua
funcionando com a ULTIMA copia de produtos.json e dos audios que ja
tinha salvo em cache (modo "offline" automatico).
"""

import ujson as json
import network
import urequests
from machine import I2C, I2S, Pin
from struct import unpack
from time import sleep_ms, ticks_diff, ticks_ms

from pn532 import NFC, NFCError, PN532Error, PN532Timeout

# ===========================================================================
# 1) WIFI E PAGINA DE PRODUTOS (GitHub Pages)
# ===========================================================================

WIFI_SSID = "Popota"
WIFI_SENHA = "Popota264"

# URL do site publicado (sem barra no final). Ex.:
# "https://seu-usuario.github.io/anel-rfid-produtos"
BASE_URL = "https://gabmenacho.github.io/anel_rfid"
URL_PRODUTOS = BASE_URL + "/produtos.json"

CACHE_PRODUTOS = "/produtos_cache.json"
PASTA_AUDIO_CACHE = "/audio_cache"

TIMEOUT_WIFI_S = 20

# ===========================================================================
# 2) PINOS (identico a V1 -- ver anel_rfid_v1.py para o porque de cada um)
# ===========================================================================

AUTODETECTAR = True

CANDIDATOS_FIACAO = (
    (1, 43, 44), (1, 44, 43),   # ESP32-S3 ES3C28P/N28P (conector "Serial Port")
    (2, 3, 2), (2, 2, 3),       # conector de expansao (GPIO2/GPIO3) desta placa
    (2, 17, 16), (2, 16, 17),   # ESP32-WROOM generica (pinos 17/16)
)

NFC_CFG_FILE = "/nfc_cfg.txt"

UART_NUM = 1
UART_TX = 43
UART_RX = 44

ES8311_ADDR = 0x18
PIN_AUDIO_EN = 1
PIN_BCLK = 5
PIN_DOUT = 8
PIN_WS = 7
PIN_I2C_SCL = 15
PIN_I2C_SDA = 16

# ===========================================================================
# 3) WIFI
# ===========================================================================


def conectar_wifi(tentativas=3):
    """Conecta ao WiFi, reiniciando a interface a cada tentativa.

    O ESP32 as vezes fica com o driver WiFi num estado invalido (sobra de
    uma execucao anterior no viper-ide sem desligar a placa, ou de um
    reset por software/Ctrl+D) e wlan.connect() falha com
    "Wifi Internal State Error". Desligar e religar a interface antes de
    cada tentativa resolve a maioria dos casos; se persistir, so um
    reset FISICO da placa (botao RESET ou desligar/ligar a energia) --
    nao Ctrl+D -- limpa o driver de verdade.
    """
    wlan = network.WLAN(network.STA_IF)

    for tentativa in range(1, tentativas + 1):
        try:
            if wlan.active():
                wlan.active(False)
                sleep_ms(300)
            wlan.active(True)
            sleep_ms(300)

            if wlan.isconnected():
                print("WiFi ja conectado - IP:", wlan.ifconfig()[0])
                return True

            print("Conectando ao WiFi '{}' (tentativa {}/{})...".format(
                WIFI_SSID, tentativa, tentativas))
            wlan.connect(WIFI_SSID, WIFI_SENHA)
        except OSError as e:
            print("  Erro ao iniciar conexao WiFi ({}); tentando de novo...".format(e))
            sleep_ms(500)
            continue

        inicio = ticks_ms()
        falhou = False
        while not wlan.isconnected():
            if ticks_diff(ticks_ms(), inicio) > TIMEOUT_WIFI_S * 1000:
                print("  Timeout nesta tentativa.")
                falhou = True
                break
            sleep_ms(200)

        if not falhou:
            print("  WiFi OK - IP:", wlan.ifconfig()[0])
            return True

    print("  Nao foi possivel conectar ao WiFi apos {} tentativa(s) (modo "
          "offline/cache). Se o erro persistir, de um RESET FISICO na "
          "placa (nao Ctrl+D) e confira SSID/senha.".format(tentativas))
    return False


# ===========================================================================
# 4) BUSCA DE PRODUTOS E AUDIO NA PAGINA (com cache local)
# ===========================================================================


def _garantir_pasta(caminho):
    import os

    try:
        os.mkdir(caminho)
    except OSError:
        pass  # ja existe


def baixar_produtos(wifi_ok):
    """Busca produtos.json na pagina; cai para o cache local se preciso."""
    if wifi_ok:
        try:
            resp = urequests.get(URL_PRODUTOS)
            try:
                dados = resp.json()
            finally:
                resp.close()
            with open(CACHE_PRODUTOS, "w") as f:
                json.dump(dados, f)
            produtos = dados.get("produtos", {})
            print("  produtos.json atualizado ({} produto(s)).".format(len(produtos)))
            return produtos
        except Exception as e:
            print("  Falha ao baixar produtos.json ({}); tentando cache local.".format(e))

    try:
        with open(CACHE_PRODUTOS) as f:
            dados = json.load(f)
        produtos = dados.get("produtos", {})
        print("  Usando cache local ({} produto(s)).".format(len(produtos)))
        return produtos
    except OSError:
        print("  Sem cache local disponivel e sem rede -- nenhum produto carregado.")
        return {}


def _caminho_cache_audio(caminho_audio):
    nome = caminho_audio.rsplit("/", 1)[-1]
    return PASTA_AUDIO_CACHE + "/" + nome


def obter_audio_local(caminho_audio, wifi_ok):
    """Devolve o caminho LOCAL do audio do produto, baixando-o da pagina
    se ainda nao estiver em cache. None se nao houver audio disponivel."""
    if not caminho_audio:
        return None

    destino = _caminho_cache_audio(caminho_audio)
    try:
        with open(destino, "rb"):
            return destino  # ja esta em cache, nao precisa baixar de novo
    except OSError:
        pass

    if not wifi_ok:
        print("  [audio] Sem rede e sem cache para '{}'.".format(caminho_audio))
        return None

    url = BASE_URL + "/" + caminho_audio.lstrip("/")
    print("  Baixando audio: {}".format(url))
    try:
        resp = urequests.get(url)
        try:
            conteudo = resp.content
        finally:
            resp.close()
        _garantir_pasta(PASTA_AUDIO_CACHE)
        with open(destino, "wb") as f:
            f.write(conteudo)
        return destino
    except Exception as e:
        print("  Falha ao baixar audio ({}).".format(e))
        return None


# ===========================================================================
# 5) AUDIO - identico a V1 (ES8311 + WAV da flash)
# ===========================================================================


def _escrever_reg(i2c, reg, valor):
    i2c.writeto_mem(ES8311_ADDR, reg, bytes((valor,)))


def _ler_reg(i2c, reg):
    return i2c.readfrom_mem(ES8311_ADDR, reg, 1)[0]


def _iniciar_es8311_playback(i2c):
    _escrever_reg(i2c, 0x00, 0x1F)
    sleep_ms(20)
    _escrever_reg(i2c, 0x00, 0x00)
    sleep_ms(20)
    _escrever_reg(i2c, 0x44, 0x08)
    for reg, valor in (
        (0x01, 0x30), (0x02, 0x00), (0x03, 0x10), (0x16, 0x24),
        (0x04, 0x10), (0x05, 0x00), (0x0B, 0x00), (0x0C, 0x00),
        (0x10, 0x1F), (0x11, 0x7F), (0x00, 0x80),
    ):
        _escrever_reg(i2c, reg, valor)
    for reg, valor in (
        (0x01, 0xBF), (0x02, 0x18), (0x03, 0x10), (0x04, 0x10),
        (0x05, 0x00), (0x06, 0x03), (0x07, 0x00), (0x08, 0xFF),
        (0x09, 0x0C), (0x0A, 0x4C), (0x13, 0x10), (0x1B, 0x0A), (0x1C, 0x6A),
    ):
        _escrever_reg(i2c, reg, valor)
    for reg, valor in (
        (0x17, 0xBF), (0x0E, 0x02), (0x12, 0x00), (0x14, 0x1A),
        (0x0D, 0x01), (0x15, 0x40), (0x37, 0x08), (0x45, 0x00),
        (0x44, 0x58), (0x32, 0xBF),
    ):
        _escrever_reg(i2c, reg, valor)
    _escrever_reg(i2c, 0x31, _ler_reg(i2c, 0x31) & 0x9F)
    sleep_ms(50)


def _ler_cabecalho_wav(arquivo):
    cabecalho = arquivo.read(12)
    if cabecalho[0:4] != b"RIFF" or cabecalho[8:12] != b"WAVE":
        raise ValueError("Arquivo nao e um WAV valido")
    canais = taxa = bits = None
    while True:
        bloco_id = arquivo.read(4)
        if len(bloco_id) < 4:
            raise ValueError("WAV sem bloco 'data'")
        (tamanho,) = unpack("<I", arquivo.read(4))
        if bloco_id == b"fmt ":
            fmt = arquivo.read(tamanho)
            _, canais, taxa, _, _, bits = unpack("<HHIIHH", fmt[:16])
        elif bloco_id == b"data":
            return canais, taxa, bits, tamanho
        else:
            arquivo.seek(tamanho, 1)


def tocar_wav(caminho):
    i2c = None
    i2s = None
    audio_en = Pin(PIN_AUDIO_EN, Pin.OUT, value=1)
    try:
        i2c = I2C(0, scl=Pin(PIN_I2C_SCL), sda=Pin(PIN_I2C_SDA), freq=100000)
        if ES8311_ADDR not in i2c.scan():
            print("  [audio] Codec ES8311 nao respondeu; pulando audio.")
            return False
        with open(caminho, "rb") as arquivo:
            canais, taxa, bits, tamanho_dados = _ler_cabecalho_wav(arquivo)
            formato = I2S.STEREO if canais == 2 else I2S.MONO
            i2s = I2S(
                0,
                sck=Pin(PIN_BCLK),
                ws=Pin(PIN_WS),
                sd=Pin(PIN_DOUT),
                mode=I2S.TX,
                bits=bits,
                format=formato,
                rate=taxa,
                ibuf=8192,
            )
            _iniciar_es8311_playback(i2c)
            sleep_ms(30)
            audio_en.value(0)
            sleep_ms(10)
            restante = tamanho_dados
            bloco = bytearray(2048)
            while restante > 0:
                n = arquivo.readinto(bloco, min(len(bloco), restante))
                if not n:
                    break
                i2s.write(bloco[:n] if n < len(bloco) else bloco)
                restante -= n
            silencio = bytearray(1024)
            i2s.write(silencio)
            sleep_ms(80)
        return True
    except OSError:
        print("  [audio] Arquivo '{}' nao encontrado na flash.".format(caminho))
        return False
    finally:
        audio_en.value(1)
        if i2s is not None:
            i2s.deinit()
        if i2c is not None:
            del i2c


# ===========================================================================
# 6) NFC - leitura de UID (identico a V1)
# ===========================================================================


def uid_para_texto(uid_bytes):
    return ":".join("{:02X}".format(b) for b in uid_bytes)


def descobrir_uid(nfc):
    print("Aproxime a tag que deseja cadastrar (Ctrl-C para sair)...")
    while True:
        tag = nfc.wait_for_tag()
        print("UID encontrado:", uid_para_texto(tag.uid), "| tipo:", tag.type)
        nfc.device.release()
        sleep_ms(1000)


# ===========================================================================
# 7) AUTODETECCAO DA FIACAO DO NFC (identico a V1)
# ===========================================================================


def _testar_fiacao(uart, tx, rx):
    from pn532 import PN532

    dev = None
    try:
        dev = PN532(uart, tx, rx)
        dev.firmware()
        return True
    except Exception:
        return False
    finally:
        if dev is not None:
            try:
                dev.uart.deinit()
            except Exception:
                pass


def _carregar_cfg_fiacao():
    try:
        with open(NFC_CFG_FILE) as f:
            partes = f.read().strip().split(",")
        if len(partes) == 3:
            return tuple(int(p) for p in partes)
    except (OSError, ValueError):
        pass
    return None


def _salvar_cfg_fiacao(uart, tx, rx):
    try:
        with open(NFC_CFG_FILE, "w") as f:
            f.write("{},{},{}".format(uart, tx, rx))
    except OSError as e:
        print("  (nao foi possivel salvar {}: {})".format(NFC_CFG_FILE, e))


def _autodetectar_fiacao():
    print("Detectando a fiacao do PN532...")
    for uart, tx, rx in CANDIDATOS_FIACAO:
        if _testar_fiacao(uart, tx, rx):
            print("  OK: UART{} TX{} RX{}".format(uart, tx, rx))
            _salvar_cfg_fiacao(uart, tx, rx)
            return uart, tx, rx
        print("  -- UART{} TX{} RX{}: sem resposta".format(uart, tx, rx))
    return None


def descobrir_fiacao():
    cfg = _carregar_cfg_fiacao()
    if cfg is not None:
        uart, tx, rx = cfg
        print("Config salva: UART{} TX{} RX{} -> testando...".format(uart, tx, rx))
        if _testar_fiacao(uart, tx, rx):
            print("  OK (boot rapido, sem varredura).")
            return cfg
        print("  Config salva falhou; voltando a auto-deteccao.")
    return _autodetectar_fiacao()


# ===========================================================================
# 8) LOOP PRINCIPAL
# ===========================================================================


def falar_resultado(produto, wifi_ok):
    if produto is None:
        print("  >> Produto NAO cadastrado na pagina. Cadastre pelo painel /admin/.")
        return
    print("  >> Produto: {}".format(produto.get("nome", "?")))
    print("  >> Cor    : {}".format(produto.get("cor", "?")))
    print("  >> Marca  : {}".format(produto.get("marca", "?")))
    caminho_local = obter_audio_local(produto.get("audio"), wifi_ok)
    if caminho_local:
        tocar_wav(caminho_local)


def loop_principal():
    wifi_ok = conectar_wifi()
    produtos = baixar_produtos(wifi_ok)

    if AUTODETECTAR:
        cfg = descobrir_fiacao()
        if cfg is None:
            print("Nenhuma fiacao respondeu. Verifique alimentacao/GND e as")
            print("linhas TX/RX do PN532, ou ajuste CANDIDATOS_FIACAO.")
            return
        uart, tx, rx = cfg
    else:
        uart, tx, rx = UART_NUM, UART_TX, UART_RX
        print("Modo manual: UART{} TX{} RX{}.".format(uart, tx, rx))

    nfc = NFC(uart=uart, tx=tx, rx=rx, debug=False)
    try:
        ic, ver, rev, sup = nfc.device.firmware()
        print("PN532 OK - firmware {}.{} (UART{} TX{} RX{})".format(
            ver, rev, uart, tx, rx))
    except PN532Error as e:
        print("Falha ao falar com o PN532:", e)
        return

    print("Anel RFID pronto ({} produto(s) carregado(s)). Aproxime um produto "
          "(Ctrl-C para sair).".format(len(produtos)))
    while True:
        try:
            tag = nfc.wait_for_tag()
        except KeyboardInterrupt:
            print("Encerrado pelo usuario.")
            return
        except PN532Timeout:
            continue

        uid_txt = uid_para_texto(tag.uid)
        print("\nTag detectada - UID:", uid_txt, "| tipo:", tag.type)
        produto = produtos.get(uid_txt)
        falar_resultado(produto, wifi_ok)

        try:
            nfc.device.release()
        except NFCError:
            pass
        sleep_ms(1500)


if __name__ == "__main__":
    loop_principal()