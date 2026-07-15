# MCP HTTPService 0.9.0

Read-only HTTP extension used by 1C AI Inspector. This custom build is based
on the `mcp-1c` `v1.8.4` source that matches the deployed `mcp-1c.exe`.

## Release changes

- the 1C extension metadata reports version `0.9.0`;
- `GET /version` reports `0.9.0`;
- vendor is `Michael Edel`;
- the extension remains an `AddOn` and does not add write endpoints;
- the upstream HTTP contract is unchanged.

## Artifact

`dist/MCP_HTTPService_0.9.0.cfe`

SHA-256:

```text
259304B716CDB268D01E2A8EBEA45C2FBB0A87D7E7829324FC853E38E7F0E141
```

## Build on Windows

All temporary files and build infobases are placed on drive `D:` by default:

```powershell
.\integrations\mcp-httpservice\build-extension.ps1
```

The build script never uses `InfoBase1`. It loads the XML sources into a
separate build infobase and writes the artifact under `D:\CodexBuild`.

## Installation

Before updating the extension, close active 1C sessions and create a backup of
the currently installed `.cfe`. Load `dist/MCP_HTTPService_0.9.0.cfe` through
the extension management window and update the database configuration.

## Provenance

The baseline extension sources come from
`https://github.com/feenlace/mcp-1c`, tag `v1.8.4`, commit
`3735ae972da9cf18f8090a8114afed3fe8fbca13`. The upstream project declares
the MIT license in its repository documentation.
