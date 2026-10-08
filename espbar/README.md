# EspBar

Une « DolphinBar Wi-Fi » : un ESP32 (DevKit classique), ou deux, connecte les Wiimotes en Bluetooth
et les envoie, par le Wi-Fi, au Dolphin de la session Wii de l'appareil Moonlight relié
(Wolfy › Wii › onglet **EspBar**). Les rapports HID passent tels quels : Dolphin les voit
comme de vraies Wiimotes (pointeur IR, Nunchuk, MotionPlus, haut-parleur, vibreur).

```
Wiimotes ──Bluetooth──▶ ESP32 ──Wi-Fi, WebSocket──▶ Wolfy (relais) ──TCP local 8421──▶ Dolphin de la session reliée
Wiimotes ──Bluetooth──▶ ESP32 BT ──UART──▶ ESP32 Wi-Fi ──Wi-Fi, WebSocket──▶ …            (2 ESP32)
```

Deux variantes, au choix à l'injection (Wolfy › Wii › EspBar) :

- **1 ESP32** (`firmware.bin`, `firmware/single`) : Wi-Fi et Bluetooth se partagent l'antenne,
  ~37 rapports/s par Wiimote.
- **2 ESP32** (`firmware-dual.bin` + `firmware-bt.bin`, `firmware/wifi` + `firmware/bt`) : l'ESP32
  Bluetooth a la radio pour lui seul, jusqu'à 100 rapports/s par Wiimote (leur cadence maximale).
  On injecte une fois l'ESP32 Bluetooth seul en USB (`firmware-bt.bin`), puis l'ESP32 Wi-Fi. Celui-ci
  porte le programme de l'ESP32 Bluetooth : à son démarrage, si l'autre n'a pas le même, il le lui
  envoie par l'UART (OTA, dans son 2e emplacement ; le bootloader revient à l'ancien si le nouveau ne
  lui répond pas). Si GPIO0 est câblé, il peut aussi l'écrire par son bootloader ROM
  ([esp-serial-flasher](https://github.com/espressif/esp-serial-flasher)), même vierge : plus besoin
  de l'injection USB. Il relaie ensuite leurs trames, UART 921600 bauds.

### Câblage des 2 ESP32

| ESP32 Wi-Fi (USB, injecté par Wolfy) |   | ESP32 Bluetooth |
|---|---|---|
| TX2 (GPIO17) | → | RX0 (GPIO3) |
| RX2 (GPIO16) | ← | TX0 (GPIO1) |
| D25 | → | EN |
| D26 | → | GPIO0 (BOOT), facultatif |
| VIN (5 V) | — | VIN (5 V) |
| GND | — | GND |

Sur un DevKit 30 broches, GPIO0 n'est pas sorti : on s'en passe (injection USB une fois de l'ESP32
Bluetooth), ou on soude le fil sur la patte du bouton BOOT côté puce (l'autre va à GND). Le bouton de recherche (D4 ↔ 3V3) et la LED de recherche (D15) vont sur
l'ESP32 Bluetooth. Ne pas brancher l'ESP32 Bluetooth en USB pendant qu'il est relié (son
convertisseur USB-série est sur les mêmes broches RX0 / TX0).

- **ESP32** (`firmware/`) : ESP-IDF + [BTstack](https://github.com/bluekitchen/btstack)
  (recherche des Wiimotes, canaux HID L2CAP, appairage). Cherche les Wiimotes (1 + 2) pendant
  une session Wii de l'appareil relié tant qu'aucune n'est connectée, ou 30 s quand on maintient
  3 s le bouton (D4 ↔ 3V3) ; la LED de D15 clignote alors. Pas de recherche sinon : elle prend la
  radio aux Wiimotes connectées (~25 rapports/s au lieu de ~37).
  LED bleue de la carte (D2) : clignote = cherche Wolfy, allumée = connecté.
- **Wolfy** (`backend/wolfy/espbar_relay.py`) : l'ESP32 le joint par un WebSocket sur sa propre
  adresse, `wss://wolfy.rm4.fr/api/espbar/ws` (via SWAG, de n'importe où ; certificat vérifié)
  ou `ws://<IP du serveur>:8420/api/espbar/ws` (réseau local). Les Dolphin des sessions le
  joignent sur le port 8421 (localhost seulement). Les Wiimotes vont à la session de l'appareil relié.
  Plusieurs EspBar : chacune est reconnue par la MAC de base de sa puce (`id` de son HELLO, lue par
  le navigateur à l'injection) et a son appareil, choisi à l'injection (une EspBar par appareil), dans
  Wolfy › Wii › EspBar ; une carte inconnue y apparaît à sa première connexion.
- **Dolphin** (`images/dolphin/espbar/`) : backend « EspBar » ajouté aux vraies Wiimotes.
  Les joueurs réglés sur « Vraie Wiimote » (onglet Wolfy-Dolphin) les reçoivent.

## Compiler

```sh
espbar/build.sh        # Docker seulement : image ESP-IDF officielle, BTstack et esp-serial-flasher téléchargés
```

Produit `firmware.bin` (1 ESP32), `firmware-dual.bin` (ESP32 Wi-Fi, avec le programme de l'ESP32
Bluetooth dedans, `firmware/bt_image.py`) et `firmware-bt.bin` (ESP32 Bluetooth) : images complètes (bootloader + partitions +
appli) écrites à 0x0, intégrées à l'image Wolfy (reconstruire le conteneur `wolfy` ensuite).

```
firmware/
  components/espbar_wire/  types de trames (protocol.h), trames sur l'UART entre les 2 ESP32 (wire.c)
  single/                  1 ESP32 : wifi/main/{config,link}.c + bt/main/wiimotes.c
  wifi/                    ESP32 Wi-Fi : lien Wolfy (link.c), ESP32 Bluetooth (radio.c)
  bt/                      ESP32 Bluetooth : Wiimotes (wiimotes.c), UART0 vers l'ESP32 Wi-Fi (link.c)
```

## Mémoire flash (4 Mo, 1 ESP32 ou ESP32 Wi-Fi)

| Adresse  | Partition | Contenu |
|----------|-----------|---------|
| 0x1000   | bootloader | |
| 0x8000   | table des partitions | |
| 0x9000   | nvs | clés d'appairage Bluetooth (sur l'ESP32 Bluetooth avec 2 ESP32), calibration Wi-Fi |
| 0x10000  | factory | le programme |
| 0x3FF000 | espbar | Wi-Fi, adresse et jeton de Wolfy, écrits par Wolfy à l'injection (`EB01` + JSON) |

## Protocole (messages WebSocket binaires / TCP, les deux sens)

`u16 longueur (little endian) | u8 type | u8 emplacement | données` — types dans
`firmware/main/protocol.h` : HELLO (JSON + jeton), WIIMOTE_ON / OFF, REPORT (0xA1 / 0xA2 + rapport
HID), DROP (éteindre une Wiimote), PING (toutes les 2 s), SCAN (chercher ou non).
Entre les 2 ESP32, les mêmes trames précédées de `0xEB` et suivies d'un CRC-8 (`wire.h`) ; l'ESP32
Bluetooth y donne son adresse et l'empreinte de son programme (HELLO) et son flux toutes les 2 s (STATS),
et reçoit ses mises à jour (OTA_BEGIN / DATA par 1 Ko / END, chacune acquittée par OTA_ACK).

BTstack est gratuit pour un usage non commercial (voir sa licence).
