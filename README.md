# ResellerClub Integration for Odoo 19

Complete integration with ResellerClub HTTP API for managing domains, hosting, SSL certificates, and more directly from Odoo.

## Features

### Domain Management
- Register new domains with multiple TLD support
- Transfer domains from other registrars
- Renew domain registrations
- Manage DNS records (A, AAAA, CNAME, MX, TXT, NS, SRV)
- WHOIS privacy protection
- Theft protection (domain lock)
- Custom nameserver configuration
- DNS templates for quick setup

### Hosting Services
- Single Domain Hosting
- Multi Domain Hosting
- Reseller Hosting
- Email Hosting
- VPS Servers
- Dedicated Servers
- Plan upgrades and renewals

### SSL Certificates
- Domain Validation (DV)
- Organization Validation (OV)
- Extended Validation (EV)
- Wildcard certificates
- Multi-domain (SAN) certificates
- CSR generation
- Certificate enrollment and renewal

### Customer Management
- Automatic sync with Odoo contacts
- Create customers in ResellerClub
- Manage contacts for domain registrations
- Customer portal for self-service

### Sales Integration
- Automatic product synchronization
- Configurable pricing margins
- Order provisioning automation
- Multi-currency support

### Notifications & Automation
- Expiry reminders via email
- Activity scheduling
- Automatic status synchronization
- Scheduled cron jobs

## Installation

1. Clone this repository into your Odoo addons directory:
```bash
git clone https://github.com/iteraSoft/resellerclub-odoo-connector.git
```

2. Install Python dependencies:
```bash
pip install requests
```

3. Update your Odoo apps list and install "ResellerClub Integration"

## Configuration

1. Go to **Settings > ResellerClub**
2. Enter your ResellerClub credentials:
   - **Reseller ID**: Your ResellerClub reseller ID
   - **API Key**: Your API key from ResellerClub settings
3. Enable **Test Mode** to use the sandbox environment
4. Configure default nameservers
5. Set pricing margins for domains, hosting, and SSL
6. Click **Test Connection** to verify your credentials
7. Click **Sync Products** to import products from ResellerClub

## Usage

### Registering a Domain
1. Go to **ResellerClub > Domains**
2. Click **Create** or use the "Register Domain" wizard
3. Enter the domain name and select a customer
4. Choose registration period and privacy options
5. Click **Register Domain**

### Managing DNS
1. Open a domain record
2. Go to the **DNS Records** tab
3. Add, edit, or delete DNS records
4. Changes are automatically synced to ResellerClub

### Customer Portal
Customers can access their services at `/my`:
- View domains, hosting, and SSL certificates
- Check expiration dates
- See service details

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/resellerclub/domain/check` | POST | Check domain availability |
| `/resellerclub/domain/suggest` | POST | Get domain suggestions |
| `/resellerclub/webhook` | POST | Receive status updates |
| `/resellerclub/balance` | POST | Get account balance |

## Security

The module includes:
- Two user groups: User and Manager
- Multi-company rules for all models
- API key encryption in settings
- Masked sensitive data in logs

## Scheduled Tasks

- **Sync Domains**: Every 4 hours
- **Sync Hosting**: Every 4 hours
- **Sync SSL**: Every 4 hours
- **Sync Customers**: Every 6 hours
- **Sync Orders**: Every 2 hours
- **Expiry Notifications**: Daily
- **Clean API Logs**: Weekly

## Dependencies

- Odoo 19.0
- `sale_management`
- `account`
- `contacts`
- `product`
- `mail`
- `portal`
- `website_sale`

Python:
- `requests`

## License

LGPL-3

## Support

- Website: [iteraSoft](https://www.iterasoft.com)
- Documentation: [ResellerClub API](https://manage.resellerclub.com/kb/answer/744)

## Contributing

Contributions are welcome! Please submit pull requests to the development branch.

## Changelog

### Version 19.0.1.0.0
- Initial release for Odoo 19
- Full domain management (register, transfer, renew)
- Hosting management
- SSL certificate management
- Customer portal
- Sales integration
- Automated sync and notifications
