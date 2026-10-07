# EspBar

Une « DolphinBar Wi-Fi » : un ESP32 (DevKit classique) connecte les Wiimotes en Bluetooth et
les envoie, par le Wi-Fi, au Dolphin de la session Wii de l'appareil Moonlight relié
(Wolfy › Wii › onglet **EspBar**). Les rapports HID passent tels quels : Dolphin les voit
comme de vraies Wiimotes (pointeur IR, Nunchuk, MotionPlus, haut-parleur, vibreur).

```
Wiimotes ──Bluetooth──▶ ESP32 ──Wi-Fi, WebSocket──▶ Wolfy (relais) ──TCP local 8421──▶ Dolphin de la session reliée
```

- **ESP32** (`firmware/`) : ESP-IDF + [BTstack](https://github.com/bluekitchen/btstack)
  (recherche des Wiimotes, canaux HID L2CAP, appairage). Cherche les Wiimotes (1 + 2 ou SYNC)
  seulement quand une session Wii de l'appareil relié tourne. LED bleue : clignote = cherche
  Wolfy, allumée = connecté.
- **Wolfy** (`backend/wolfy/espbar_relay.py`) : l'ESP32 le joint par un WebSocket sur sa propre
  adresse, `wss://wolfy.rm4.fr/api/espbar/ws` (via SWAG, de n'importe où ; certificat vérifié)
  ou `ws://<IP du serveur>:8420/api/espbar/ws` (réseau local). Les Dolphin des sessions le
  joignent sur le port 8421 (localhost seulement). Les Wiimotes vont à la session de l'appareil relié.
- **Dolphin** (`images/dolphin/espbar/`) : backend « EspBar » ajouté aux vraies Wiimotes.
  Les joueurs réglés sur « Vraie Wiimote » (onglet Wolfy-Dolphin) les reçoivent.

## Compiler

```sh
espbar/build.sh        # Docker seulement : image ESP-IDF officielle, BTstack téléchargé
```

Produit `firmware.bin` : image complète (bootloader + partitions + appli) écrite à 0x0,
intégrée à l'image Wolfy (reconstruire le conteneur `wolfy` ensuite).

## Mémoire flash (4 Mo)

| Adresse  | Partition | Contenu |
|----------|-----------|---------|
| 0x1000   | bootloader | |
| 0x8000   | table des partitions | |
| 0x9000   | nvs | clés d'appairage Bluetooth, calibration Wi-Fi |
| 0x10000  | factory | le programme |
| 0x3FF000 | espbar | Wi-Fi, adresse et jeton de Wolfy, écrits par Wolfy à l'injection (`EB01` + JSON) |

## Protocole (messages WebSocket binaires / TCP, les deux sens)

`u16 longueur (little endian) | u8 type | u8 emplacement | données` — types dans
`firmware/main/protocol.h` : HELLO (JSON + jeton), WIIMOTE_ON / OFF, REPORT (0xA1 / 0xA2 + rapport
HID), DROP (éteindre une Wiimote), PING (toutes les 2 s), SCAN (chercher ou non).

BTstack est gratuit pour un usage non commercial (voir sa licence).
