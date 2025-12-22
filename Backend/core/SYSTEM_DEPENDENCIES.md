⚙️ Dependencias del sistema (System Dependencies)

Metacrawler NO depende solo de Python.
Requiere ciertas herramientas del sistema para funcionar correctamente en entornos Linux (VMs, cloud, servidores headless).

Esta sección documenta todo lo que debe instalarse en una máquina nueva antes de ejecutar el runner.

🖥️ Sistema operativo soportado

Ubuntu 20.04+

Ubuntu 22.04 (recomendado)

Debian-based Linux

Otros sistemas pueden funcionar, pero no están oficialmente soportados.

📦 Paquetes del sistema requeridos
1️⃣ Python y herramientas base
sudo apt update
sudo apt install -y \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev

2️⃣ Herramientas de compilación (requeridas por algunas dependencias)
sudo apt install -y \
    build-essential \
    gcc \
    make

3️⃣ Librerías de red y SSL

Necesarias para requests HTTPS, TLS y crawling estable.

sudo apt install -y \
    ca-certificates \
    curl \
    wget \
    openssl

4️⃣ Utilidades de archivos y sistema

Metacrawler usa y asume la existencia de estas herramientas:

sudo apt install -y \
    unzip \
    zip \
    rsync \
    file

5️⃣ YAML y soporte de parsing

Aunque PyYAML se instala vía pip, estas librerías del sistema evitan errores raros:

sudo apt install -y \
    libyaml-dev

🐍 Dependencias Python (aisladas en venv)

Metacrawler DEBE ejecutarse dentro de un virtualenv.

Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

Dependencias mínimas de Python
pip install --upgrade pip
pip install \
    pyyaml \
    requests \
    beautifulsoup4 \
    lxml


⚠️ No instalar dependencias globales
Todo debe vivir dentro del venv.

📁 Permisos y filesystem

Metacrawler requiere permisos de escritura en:

carpeta de datos persistentes (fileforge-data/)

carpeta de logs

carpeta de estado

Ejemplo recomendado:

sudo mkdir -p /opt/fileforge-data
sudo chown -R $USER:$USER /opt/fileforge-data


Y exportar variables de entorno si aplica:

export FILEFORGE_DATA_ROOT=/opt/fileforge-data

🌐 Conectividad de red

La máquina debe permitir:

Salidas HTTPS (443)

Resolución DNS

Conexiones persistentes

En cloud (OCI, AWS, etc.), verificar:

Security Lists

VCN outbound rules

No bloqueo por firewall

✅ Verificación rápida de entorno

Antes de correr el runner, podés verificar el sistema así:

python3 --version
which python3
pip --version
openssl version


Y luego:

python3 -m metacrawler.runner


Si el menú aparece correctamente, el entorno está listo.

🚫 Qué NO es dependencia del sistema

Metacrawler NO requiere:

Docker

Node.js

Browsers (Chrome, Chromium)

Selenium

Playwright

GPU

Modelos ML

El crawling es HTTP-first, no browser-based.

🧠 Nota importante

Si una VM nueva no corre Metacrawler, el problema casi siempre es uno de estos:

Falta de python3-venv

pip instalado fuera del venv

Permisos de escritura

Estructura incorrecta de clients/

Variables de entorno no exportadas

Por eso esta sección es obligatoria para cualquier despliegue nuevo.