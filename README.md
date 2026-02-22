# Casino News Scraper

Script automatizado para extraer noticias de las últimas 24 horas de una lista de sitios web y generar un reporte HTML enviado por correo electrónico.

## Configuración Local

1. Clona el repositorio.
2. Opcional: Crea un entorno virtual (`python -m venv .venv` y actívalo).
3. Instala las dependencias: `pip install -r requirements.txt`
4. Edita el archivo `sites.txt` agregando las URLs que quieres monitorear (una por línea).
5. Crea un archivo `.env` basado en `.env.example` y agrega tus credenciales.

## ¿Cómo generar una Contraseña de Aplicación en Google (Gmail)?

Para que el script y GitHub Actions puedan enviar correos desde tu cuenta de Gmail **sin comprometer tu cuenta principal y evadiendo la verificación de 2 pasos**, debes usar una "App Password".

1. Ve a tu [Cuenta de Google](https://myaccount.google.com/).
2. Busca la pestaña de **Seguridad** en el panel lateral a la izquierda.
3. Asegúrate de tener activada la **Verificación en dos pasos** (es un requisito).
4. En la barra de búsqueda superior de tu cuenta de Google, escribe **Contraseñas de aplicación** (o "App passwords").
5. Haz clic en el resultado. Te pedirá tu contraseña normal.
6. En el campo para describir la aplicación, escribe algo como "News Scraper GitHub" y haz clic en "Crear".
7. Te aparecerá un recuadro con un código de 16 letras. **Esa es tu contraseña de aplicación**.
8. Cópiala y pégala en tu archivo local `.env` como `SMTP_PASSWORD` y, más adelante, la guardaremos como un `Secret` en GitHub para que funcione automáticamente a las 7 AM.

## Uso Manual

```bash
python main.py
```
