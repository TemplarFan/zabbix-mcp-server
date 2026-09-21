# MCP Client Setup

## Configuration for MCP Clients

### Claude Desktop

Add this to your Claude Desktop `mcp.json` configuration file:

```json
{
  "mcpServers": {
    "zabbix": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/zabbix-mcp-server",
        "python",
        "src/zabbix_mcp_server.py"
      ],
      "env": {
        "ZABBIX_URL": "https://zabbix.example.com",
        "ZABBIX_TOKEN": "<your_api_token>",
        "READ_ONLY": "true"
      }
    }
  }
}
```

### Environment Variables

Replace these values in the `env` section:

- `ZABBIX_URL`: Your Zabbix server API endpoint
- `ZABBIX_TOKEN`: Your API token (or use ZABBIX_USER/ZABBIX_PASSWORD)
- `READ_ONLY`: Set to "true" for read-only mode

### Alternative Authentication

Instead of `ZABBIX_TOKEN`, you can use:

```json
"env": {
  "ZABBIX_URL": "https://zabbix.example.com",
  "ZABBIX_USER": "<username>",
  "ZABBIX_PASSWORD": "<password>",
  "READ_ONLY": "true"
}
```

### Path Configuration

Update the `--directory` path to match your installation:

```json
"args": [
  "run",
  "--directory",
  "/home/user/zabbix-mcp-server",
  "python",
  "src/zabbix_mcp_server.py"
]
```

### Using Configuration Template

You can copy the provided configuration template:

```bash
cp config/mcp.json ~/.config/claude-desktop/mcp.json
# Edit the file with your specific paths and credentials
```

## Alternative Startup Methods

### Using Startup Script

For better error handling and logging, you can use the startup script:

```json
{
  "mcpServers": {
    "zabbix": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/zabbix-mcp-server",
        "python",
        "scripts/start_server.py"
      ],
      "env": {
        "ZABBIX_URL": "https://zabbix.example.com",
        "ZABBIX_TOKEN": "<your_api_token>",
        "READ_ONLY": "true"
      }
    }
  }
}
```

### Using Environment File

Instead of setting environment variables in the MCP config, you can create a `.env` file in the project root:

```bash
# Copy the example configuration
cp config/.env.example .env

# Edit .env with your settings
ZABBIX_URL=https://your-zabbix-server.com
ZABBIX_TOKEN=your_actual_token_here
READ_ONLY=true
ZABBIX_TEST_NETWORKS=192.168.100.0/24,192.168.101.0/24
```

Then use a simpler MCP configuration:

```json
{
  "mcpServers": {
    "zabbix": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/zabbix-mcp-server",
        "python",
        "scripts/start_server.py"
      ]
    }
  }
}
```

## Testing

After configuration, restart your MCP client and test with:

```
Get all Zabbix hosts
```

The server should respond with your Zabbix host data.

## Troubleshooting

### Common Issues

**Server not starting:**
- Check that the path in `--directory` is correct
- Verify that `uv` is installed and accessible
- Run the test script: `uv run python scripts/test_server.py`

**Authentication errors:**
- Verify your Zabbix URL is correct and accessible
- Check that your API token or username/password are valid
- Ensure the Zabbix API is enabled

**Permission denied:**
- Check if read-only mode is enabled when trying to modify data
- Verify your Zabbix user has sufficient permissions

### Debug Mode

Enable debug logging by adding to your environment:

```json
"env": {
  "ZABBIX_URL": "https://zabbix.example.com",
  "ZABBIX_TOKEN": "<your_api_token>",
  "READ_ONLY": "true",
  "DEBUG": "1"
}
```

### Manual Testing

You can test the server manually before configuring your MCP client:

```bash
# Navigate to the project directory
cd /path/to/zabbix-mcp-server

# Run the test suite
uv run python scripts/test_server.py

# Start the server manually
uv run python scripts/start_server.py
```