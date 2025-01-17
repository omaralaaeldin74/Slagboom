from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from flasgger import Swagger
from datetime import datetime
import mysql.connector
import logging
import json
from azure.identity import ClientSecretCredential
from azure.keyvault.secrets import SecretClient

# Configuratie voor logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuratie laden
try:
    with open("config.json", "r") as config_file:
        config = json.load(config_file)
        logger.info("Configuratiebestand succesvol geladen.")
except FileNotFoundError:
    logger.error("Config.json bestand niet gevonden.")
    raise
except json.JSONDecodeError as e:
    logger.error(f"Fout bij het verwerken van config.json: {e}")
    raise

app = Flask(__name__)
CORS(app)
swagger = Swagger(app)

vault_url = config["vault_url"]
tenant_id = config["tenant_id"]
client_id = config["client_id"]
client_secret = config["client_secret"]

# Authenticatie met Azure Key Vault
try:
    credential = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    client = SecretClient(vault_url=vault_url, credential=credential)
    logger.info("Succesvol geauthenticeerd bij Azure Key Vault.")
except Exception as e:
    logger.error(f"Fout bij authenticatie met Key Vault: {e}")
    raise

# Geheimen ophalen uit Azure Key Vault
try:
    db_host = client.get_secret("HostDB").value
    db_name = client.get_secret("DBName").value
    db_user = client.get_secret("DBuser").value
    db_password = client.get_secret("DBpassword").value
    logger.info("Geheimen succesvol opgehaald uit Key Vault.")
except Exception as e:
    logger.error(f"Fout bij het ophalen van geheimen: {e}")
    raise

# Maak een databaseverbinding
def maak_verbinding():
    try:
        verbinding = mysql.connector.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_password
        )
        if verbinding.is_connected():
            logger.info("Databaseverbinding succesvol.")
            return verbinding
    except mysql.connector.Error as e:
        logger.error(f"Fout bij het verbinden met de database: {e}")
        return None

@app.route('/')
def home():
    # HTML voor het testen van de /api/slagboom endpoint
    html_content = """
    <!DOCTYPE html>
    <html lang="nl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>API Test</title>
    </head>
    <body>
        <h1>Slagboom API</h1>
        <form action="/api/slagboom" method="post">
            <label for="kenteken">Kenteken:</label>
            <input type="text" id="kenteken" name="kenteken" required>
            <button type="submit">Verstuur</button>
        </form>
    </body>
    </html>
    """
    return render_template_string(html_content)

@app.route('/api/slagboom', methods=['POST'])
def verwerk_slagboom():
    data = request.form
    kenteken = data.get("kenteken")
    if not kenteken:
        logger.warning("Geen kenteken ontvangen in verzoek.")
        return jsonify({"status": "mislukt", "bericht": "Kenteken is verplicht"}), 400

    verbinding = maak_verbinding()
    if verbinding is None:
        return jsonify({"status": "mislukt", "bericht": "Kan geen verbinding maken met de database"}), 500

    try:
        cursor = verbinding.cursor(buffered=True)
        # Controleer of het kenteken bestaat in de database
        cursor.execute("SELECT ID, EigenaarNaam FROM Kentekens WHERE Kenteken = %s", (kenteken,))
        resultaat = cursor.fetchone()

        if not resultaat:
            logger.warning(f"Kenteken {kenteken} niet gevonden in de database.")
            return jsonify({"status": "mislukt", "bericht": f"Kenteken {kenteken} is niet toegestaan"}), 403

        kenteken_id, eigenaar_naam = resultaat

        # Haal de laatste actie op uit het logboek
        cursor.execute("SELECT Actie FROM Logboek WHERE KentekenID = %s ORDER BY Tijdstip DESC LIMIT 1", (kenteken_id,))
        laatste_actie = cursor.fetchone()

        # Bepaal de nieuwe actie
        if laatste_actie is None or laatste_actie[0] == "vertrokken":
            nieuwe_actie = "binnengekomen"
        else:
            nieuwe_actie = "vertrokken"

        # Voeg de nieuwe actie toe aan het logboek
        cursor.execute(
            "INSERT INTO Logboek (KentekenID, Kenteken, EigenaarNaam, Actie, Tijdstip) VALUES (%s, %s, %s, %s, %s)",
            (kenteken_id, kenteken, eigenaar_naam, nieuwe_actie, datetime.now())
        )
        verbinding.commit()

        logger.info(f"Actie {nieuwe_actie} succesvol verwerkt voor kenteken {kenteken}.")
        return jsonify({"status": "succes", "bericht": f"{eigenaar_naam} is succesvol {nieuwe_actie}."}), 200

    except Exception as e:
        logger.error(f"Fout bij het verwerken van verzoek: {e}")
        return jsonify({"status": "mislukt", "bericht": f"Fout bij verwerken verzoek: {e}"}), 500
    finally:
        verbinding.close()

@app.route('/api/logboek', methods=['GET'])
def logboek():
    verbinding = maak_verbinding()
    if verbinding is None:
        return jsonify({"status": "mislukt", "bericht": "Kan geen verbinding maken met de database"}), 500

    try:
        cursor = verbinding.cursor()
        cursor.execute("""
            SELECT l.LogboekID, l.Kenteken, l.EigenaarNaam, l.Actie, l.Tijdstip
            FROM Logboek l
            ORDER BY l.Tijdstip DESC
        """)
        logboek = cursor.fetchall()

        logger.info("Logboekgegevens succesvol opgehaald.")
        return jsonify([
            {
                "logboek_id": row[0],
                "kenteken": row[1],
                "eigenaar_naam": row[2],
                "actie": row[3],
                "tijdstip": row[4].strftime('%Y-%m-%d %H:%M:%S')
            }
            for row in logboek
        ])

    except Exception as e:
        logger.error(f"Fout bij het ophalen van logboek: {e}")
        return jsonify({"status": "mislukt", "bericht": "Fout bij ophalen logboek"}), 500
    finally:
        verbinding.close()

# Zorg ervoor dat de Flask-app persistent draait in een Docker-container
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=4000)
