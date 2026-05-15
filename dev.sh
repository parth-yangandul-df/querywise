#!/bin/bash

# QueryWise Native Development Script
# Usage: ./dev.sh [start|stop|restart|status|logs|db|clean] [service]
#
# Works on Windows (Git Bash) and Unix-like systems

# Do NOT use set -e — it causes premature exits in Git Bash on Windows
set +e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# =============================================================================
# Constants
# =============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Ports
PORT_DB=5434
PORT_BACKEND=8000
PORT_FRONTEND=5174
PORT_ANGULAR=4200
PORT_OLLAMA=11434
PORT_REDIS=6379
PORT_MLFLOW=5003

# Paths
PIDS_DIR="$SCRIPT_DIR/dev.pids"
LOG_FILE="$SCRIPT_DIR/backend.log"

# =============================================================================
# Logging
# =============================================================================

log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC}  $1"; }

# =============================================================================
# Platform Detection
# =============================================================================

is_windows() {
    [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" || -n "$COMSPEC" ]]
}

# =============================================================================
# Port Utilities
# =============================================================================

# Reliable LISTENING check — handles both IPv4 and IPv6
is_port_in_use() {
    local port=$1
    if is_windows; then
        # Match: IPv4 (0.0.0.0:port, 127.0.0.1:port) AND IPv6 ([::1]:port, [::]:port)
        # Strip brackets from IPv6 addresses for clean matching
        netstat -ano 2>/dev/null \
            | sed 's/\[//g;s/\]//g' \
            | grep -E "TCP\s+([[0-9.:]+|[0-9a-fA-F:]+):${port}\s+.*LISTENING" \
            >/dev/null 2>&1
    else
        if command -v ss >/dev/null 2>&1; then
            ss -tlnp 2>/dev/null | grep -E ":${port}\b" >/dev/null 2>&1
        else
            netstat -tlnp 2>/dev/null | grep -E ":${port}\b" >/dev/null 2>&1
        fi
    fi
}

# Returns the PIDs (one per line) of processes holding a port LISTENING (IPv4 + IPv6)
get_pids_on_port() {
    local port=$1
    if is_windows; then
        # Strip brackets from IPv6 addresses for clean extraction
        netstat -ano 2>/dev/null \
            | sed 's/\[//g;s/\]//g' \
            | grep -E "TCP\s+([[0-9.:]+|[0-9a-fA-F:]+):${port}\s+.*LISTENING" \
            | awk '{print $NF}' \
            | sort -u
    else
        if command -v lsof >/dev/null 2>&1; then
            lsof -ti ":${port}" 2>/dev/null
        elif command -v ss >/dev/null 2>&1; then
            ss -tlnp 2>/dev/null \
                | grep -E ":${port}\b" \
                | grep -oP 'pid=\K[0-9]+'
        fi
    fi
}

# On Windows, kill all processes on a port using PowerShell (bypasses MSYS PID mismatch)
kill_port_windows_ps() {
    local port=$1
    powershell.exe -NoProfile -Command "
        \$conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if (\$conns) {
            \$conns | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique | ForEach-Object {
                Stop-Process -Id \$_ -Force -ErrorAction SilentlyContinue
            }
        }
    " >/dev/null 2>&1
}

# Poll until port becomes active (or timeout)
wait_for_port() {
    local port=$1
    local retries=${2:-15}
    while [[ $retries -gt 0 ]]; do
        if is_port_in_use "$port"; then
            return 0
        fi
        sleep 1
        (( retries-- )) || true
    done
    return 1
}

# =============================================================================
# Generic Stop Helper
# =============================================================================

# Kills the process(es) on a port, then falls back to the saved .pid file.
# Usage: stop_service <service_name> <port>
stop_service() {
    local service_name=$1
    local port=$2
    local pid_file="$PIDS_DIR/${service_name}.pid"

    log_step "Stopping ${service_name}..."

    # --- Method 1: kill by port ---
    if is_windows; then
        # Use PowerShell to avoid MSYS/Windows PID mismatch with taskkill
        kill_port_windows_ps "$port"
        for pid in $(get_pids_on_port "$port"); do
            [[ -z "$pid" ]] && continue
            log_info "  Killing PID $pid on port $port"
            taskkill //F //PID "$pid" >/dev/null 2>&1 || true
        done
    else
        for pid in $(get_pids_on_port "$port"); do
            [[ -z "$pid" ]] && continue
            log_info "  Sending SIGTERM to PID $pid on port $port"
            kill -TERM "$pid" 2>/dev/null || true
        done
        # Give processes a moment to exit cleanly before hard-killing
        sleep 2
        for pid in $(get_pids_on_port "$port"); do
            [[ -z "$pid" ]] && continue
            log_info "  Sending SIGKILL to PID $pid on port $port"
            kill -9 "$pid" 2>/dev/null || true
        done
    fi

    # --- Method 2: kill saved PID (handles cases where port detection misses) ---
    if [[ -f "$pid_file" ]]; then
        local saved_pid
        saved_pid=$(cat "$pid_file" 2>/dev/null)
        if [[ -n "$saved_pid" ]]; then
            log_info "  Killing saved PID $saved_pid for ${service_name}"
            if is_windows; then
                taskkill //F //PID "$saved_pid" >/dev/null 2>&1 || true
            else
                kill -9 "$saved_pid" 2>/dev/null || true
            fi
        fi
        rm -f "$pid_file"
    fi

    # --- Verify port was released ---
    sleep 1
    if is_port_in_use "$port"; then
        log_warn "${service_name} port $port is still in use — manual cleanup may be needed"
    else
        log_info "${service_name} stopped"
    fi
}

# =============================================================================
# Docker / PostgreSQL
# =============================================================================

# Resolve the right docker compose invocation
_docker_compose() {
    if command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    else
        docker compose "$@"
    fi
}

start_postgresql() {
    log_step "Starting PostgreSQL on port $PORT_DB..."

    if is_port_in_use $PORT_DB; then
        log_warn "PostgreSQL already running on port $PORT_DB"
        return 0
    fi

    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker not found. Please install Docker."
        return 1
    fi

    # Try docker compose first, then a bare docker run as fallback
    if _docker_compose up -d app-db 2>/dev/null; then
        : # success
    else
        docker run -d \
            --name querywise-postgres \
            -e POSTGRES_DB=saras_metadata \
            -e POSTGRES_USER=parthy \
            -e POSTGRES_PASSWORD=querywise_app \
            -p "$PORT_DB:5432" \
            pgvector/pgvector:pg16 2>/dev/null || true
    fi

    if wait_for_port $PORT_DB 10; then
        log_info "PostgreSQL started"
    else
        log_error "PostgreSQL failed to start — check Docker"
        return 1
    fi
}

stop_postgresql() {
    log_step "Stopping PostgreSQL..."
    _docker_compose stop app-db 2>/dev/null || docker stop querywise-postgres 2>/dev/null || true
    log_info "PostgreSQL stopped"
}

# =============================================================================
# Redis
# =============================================================================

start_redis() {
    log_step "Starting Redis on port $PORT_REDIS..."

    if is_port_in_use $PORT_REDIS; then
        log_warn "Redis already running on port $PORT_REDIS"
        return 0
    fi

    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker not found. Please install Docker."
        return 1
    fi

    if _docker_compose up -d redis 2>/dev/null; then
        : # success
    else
        # Try to start existing container first, then create new if not exists
        docker start querywise-redis 2>/dev/null || \
            docker run -d \
                --name querywise-redis \
                -p "$PORT_REDIS:6379" \
                redis:7-alpine
    fi

    if wait_for_port $PORT_REDIS 10; then
        log_info "Redis started"
    else
        log_error "Redis failed to start — check Docker"
        return 1
    fi
}

stop_redis() {
    log_step "Stopping Redis..."
    _docker_compose stop redis 2>/dev/null || docker stop querywise-redis 2>/dev/null || true
    log_info "Redis stopped"
}

# =============================================================================
# MLflow
# =============================================================================

start_mlflow() {
    log_step "Starting MLflow on port $PORT_MLFLOW..."

    if is_port_in_use $PORT_MLFLOW; then
        log_warn "MLflow already running on port $PORT_MLFLOW"
        return 0
    fi

    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker not found. Please install Docker."
        return 1
    fi

    if _docker_compose up -d mlflow 2>/dev/null; then
        : # success
    else
        log_error "Failed to start MLflow — check docker-compose.yml"
        return 1
    fi

    if wait_for_port $PORT_MLFLOW 15; then
        log_info "MLflow started"
    else
        log_error "MLflow failed to start — check docker compose logs"
        return 1
    fi
}

stop_mlflow() {
    log_step "Stopping MLflow..."
    _docker_compose stop mlflow 2>/dev/null || true
    log_info "MLflow stopped"
}

# =============================================================================
# Ollama — status check only; it is a system-managed service
# =============================================================================

check_ollama() {
    is_port_in_use $PORT_OLLAMA
}

# =============================================================================
# Backend
# =============================================================================

start_backend() {
    log_step "Starting Backend on port $PORT_BACKEND..."

    if is_port_in_use $PORT_BACKEND; then
        log_warn "Backend already running on port $PORT_BACKEND"
        return 0
    fi

    local pid_file="$PIDS_DIR/backend.pid"

    # Ensure venv exists
    if [[ ! -d "$SCRIPT_DIR/backend/.venv" ]]; then
        log_info "Creating Python virtual environment..."
        python -m venv "$SCRIPT_DIR/backend/.venv"
    fi

    # Ensure deps are installed
    if is_windows; then
        local python_bin="$SCRIPT_DIR/backend/.venv/Scripts/python"
        local activate="source '$SCRIPT_DIR/backend/.venv/Scripts/activate'"
    else
        local python_bin="$SCRIPT_DIR/backend/.venv/bin/python"
        local activate="source '$SCRIPT_DIR/backend/.venv/bin/activate'"
    fi

    if ! "$python_bin" -c "import uvicorn" 2>/dev/null; then
        log_info "Installing backend dependencies..."
        if is_windows; then
            "$SCRIPT_DIR/backend/.venv/Scripts/pip" install -e "$SCRIPT_DIR/backend[llm,dev,sqlserver]" 2>&1 | tee -a "$LOG_FILE" || true
        else
            "$SCRIPT_DIR/backend/.venv/bin/pip" install -e "$SCRIPT_DIR/backend[llm,dev,sqlserver]" 2>&1 | tee -a "$LOG_FILE" || true
        fi
    fi

    mkdir -p "$PIDS_DIR" 2>/dev/null || true

    # The subshell writes its own PID before exec-ing uvicorn.
    # This way $pid_file holds the actual uvicorn process PID, not the wrapper bash PID.
    if is_windows; then
        bash -c "
            ${activate}
            cd '$SCRIPT_DIR/backend'
            echo \$\$ > '$pid_file'
            exec uvicorn app.main:app --host 0.0.0.0 --port $PORT_BACKEND --reload
        " >> "$LOG_FILE" 2>&1 &
    else
        bash -c "
            ${activate}
            cd '$SCRIPT_DIR/backend'
            echo \$\$ > '$pid_file'
            exec uvicorn app.main:app --host 0.0.0.0 --port $PORT_BACKEND --reload
        " >> "$LOG_FILE" 2>&1 &
    fi

    if wait_for_port $PORT_BACKEND 20; then
        log_info "Backend started (PID: $(cat "$pid_file" 2>/dev/null || echo unknown))"
    else
        log_warn "Backend may not have started — check $LOG_FILE"
    fi
}

stop_backend() {
    log_step "Stopping backend (watchdog-aware)..."
    local pid_file="$PIDS_DIR/backend.pid"

    # On Windows, kill via PowerShell first (bypasses MSYS/Windows PID mismatch)
    if is_windows; then
        kill_port_windows_ps "$PORT_BACKEND"
    fi

    # Kill watchdog FIRST — prevents it from respawning the child worker
    if [[ -f "$pid_file" ]]; then
        local saved_pid
        saved_pid=$(cat "$pid_file" 2>/dev/null)
        if [[ -n "$saved_pid" ]]; then
            log_info "  Killing watchdog PID $saved_pid"
            if is_windows; then
                taskkill //F //PID "$saved_pid" >/dev/null 2>&1 || true
            else
                kill -9 "$saved_pid" 2>/dev/null || true
            fi
        fi
        rm -f "$pid_file"
    fi

    # Brief pause for watchdog to fully exit
    sleep 1

    # Kill any lingering child worker still holding the port
    if is_windows; then
        kill_port_windows_ps "$PORT_BACKEND"
    fi
    for pid in $(get_pids_on_port "$PORT_BACKEND"); do
        [[ -z "$pid" ]] && continue
        log_info "  Killing lingering worker PID $pid on port $PORT_BACKEND"
        if is_windows; then
            taskkill //F //PID "$pid" >/dev/null 2>&1 || true
        else
            kill -9 "$pid" 2>/dev/null || true
        fi
    done

    sleep 1

    # Final sweep — kill any remaining Python processes (uvicorn workers, reloaders, etc.)
    if is_windows; then
        powershell.exe -NoProfile -Command "
            Get-Process python* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        " >/dev/null 2>&1
    fi

    if is_port_in_use "$PORT_BACKEND"; then
        log_warn "Backend port $PORT_BACKEND still in use — manual cleanup may be needed"
    else
        log_info "Backend stopped"
    fi
}

# =============================================================================
# Frontend
# =============================================================================

start_frontend() {
    log_step "Starting Frontend on port $PORT_FRONTEND..."

    if is_port_in_use $PORT_FRONTEND; then
        log_warn "Frontend already running on port $PORT_FRONTEND"
        return 0
    fi

    local pid_file="$PIDS_DIR/frontend.pid"
    mkdir -p "$PIDS_DIR" 2>/dev/null || true

    if [[ ! -d "$SCRIPT_DIR/frontend/node_modules" ]]; then
        log_info "Installing frontend dependencies..."
        npm install --prefix "$SCRIPT_DIR/frontend" 2>/dev/null || true
    fi

    bash -c "
        cd '$SCRIPT_DIR/frontend'
        echo \$\$ > '$pid_file'
        exec npm run dev
    " >/dev/null 2>&1 &

    if wait_for_port $PORT_FRONTEND 20; then
        log_info "Frontend started (PID: $(cat "$pid_file" 2>/dev/null || echo unknown))"
    else
        log_warn "Frontend may not have started — check manually"
    fi
}

stop_frontend() {
    stop_service "frontend" $PORT_FRONTEND
}

# =============================================================================
# Angular Test App
# =============================================================================

start_angular() {
    log_step "Starting Angular Test App on port $PORT_ANGULAR..."

    if is_port_in_use $PORT_ANGULAR; then
        log_warn "Angular Test App already running on port $PORT_ANGULAR"
        return 0
    fi

    if [[ ! -d "$SCRIPT_DIR/angular-test" ]]; then
        log_warn "Angular test app not found at $SCRIPT_DIR/angular-test — skipping"
        return 0
    fi

    local pid_file="$PIDS_DIR/angular.pid"
    mkdir -p "$PIDS_DIR" 2>/dev/null || true

    if [[ ! -d "$SCRIPT_DIR/angular-test/node_modules" ]]; then
        log_info "Installing Angular test app dependencies..."
        npm install --prefix "$SCRIPT_DIR/angular-test" 2>/dev/null || true
    fi

    # Run fully detached (no console window) — survives terminal close
    if is_windows; then
        bash -c "
            cd '$SCRIPT_DIR/angular-test'
            echo \$\$ > '$pid_file'
            exec npx ng serve --port $PORT_ANGULAR
        " >/dev/null 2>&1 &
    else
        bash -c "
            cd '$SCRIPT_DIR/angular-test'
            echo \$\$ > '$pid_file'
            exec npx ng serve --port $PORT_ANGULAR
        " >/dev/null 2>&1 &
    fi

    # Wait for port to be available — give it 45s (Angular is slow to start)
    if wait_for_port $PORT_ANGULAR 45; then
        log_info "Angular Test App started on port $PORT_ANGULAR"
    else
        log_warn "Angular Test App may not have started — check manually with npm run start --prefix angular-test"
    fi
}

stop_angular() {
    stop_service "angular" $PORT_ANGULAR
}

# =============================================================================
# Main Commands
# =============================================================================

cmd_start() {
    log_info "Starting all QueryWise services..."
    echo ""

    mkdir -p "$PIDS_DIR" 2>/dev/null || true
    _ensure_gitignore_entry

    start_postgresql || true
    echo ""

start_redis || true
    echo ""

    start_mlflow || true
    echo ""

    start_backend
    echo ""

    start_frontend
    echo ""

    start_angular
    echo ""

    log_info "All services started!"
    echo ""
    cmd_status
}

cmd_stop() {
    log_info "Stopping all QueryWise services..."
    echo ""

    stop_angular
    echo ""
    stop_frontend
    echo ""
    stop_backend
    echo ""
    stop_postgresql
    echo ""
    stop_redis
    echo ""
    stop_mlflow
    echo ""

    log_info "All services stopped"
}

# restart [service]
# If no service is given, restarts all services.
cmd_restart() {
    local service="${1:-all}"

    case "$service" in
        backend)
            stop_backend
            echo ""
            start_backend
            ;;
        frontend)
            stop_frontend
            echo ""
            start_frontend
            ;;
        angular)
            stop_angular
            echo ""
            start_angular
            ;;
        redis)
            stop_redis
            echo ""
            start_redis
            ;;
        all)
            cmd_stop
            echo ""
            cmd_start
            ;;
        *)
            log_error "Unknown service: $service"
            log_info "Valid services: backend, frontend, angular, redis"
            return 1
            ;;
    esac
}

cmd_status() {
    echo -e "${BLUE}=== QueryWise Service Status ===${NC}"
    echo ""

    local -A service_ports=(
        ["PostgreSQL"]=$PORT_DB
        ["Redis"]=$PORT_REDIS
        ["MLflow"]=$PORT_MLFLOW
        ["Ollama"]=$PORT_OLLAMA
        ["Backend"]=$PORT_BACKEND
        ["Frontend"]=$PORT_FRONTEND
        ["Angular"]=$PORT_ANGULAR
    )

    # Print in a stable order
    local ordered_services=("PostgreSQL" "Redis" "MLflow" "Ollama" "Backend" "Frontend" "Angular")
    for name in "${ordered_services[@]}"; do
        local port=${service_ports[$name]}
        if is_port_in_use "$port"; then
            echo -e "  ${GREEN}✓${NC} ${name} (port ${port}) — RUNNING"
        else
            echo -e "  ${RED}✗${NC} ${name} (port ${port}) — STOPPED"
        fi
    done

    # Show saved PID file contents if present
    if [[ -d "$PIDS_DIR" ]]; then
        local any_pid=false
        for pid_file in "$PIDS_DIR"/*.pid; do
            [[ -f "$pid_file" ]] && any_pid=true && break
        done
        if $any_pid; then
            echo ""
            echo -e "${BLUE}=== Saved PIDs ===${NC}"
            for pid_file in "$PIDS_DIR"/*.pid; do
                [[ -f "$pid_file" ]] || continue
                local svc_name
                svc_name="$(basename "$pid_file" .pid)"
                echo "  ${svc_name}: $(cat "$pid_file")"
            done
        fi
    fi

    echo ""
}

cmd_logs() {
    if [[ -f "$LOG_FILE" ]]; then
        log_info "Tailing backend logs (Ctrl+C to exit)..."
        tail -f "$LOG_FILE"
    else
        log_error "Log file not found: $LOG_FILE"
        log_info "Backend may not have been started yet"
    fi
}

cmd_db() {
    if is_port_in_use $PORT_DB; then
        stop_postgresql
    else
        start_postgresql
    fi
}

cmd_clean() {
    log_warn "Cleaning up all development processes..."
    echo ""

    local all_ports=($PORT_BACKEND $PORT_FRONTEND $PORT_ANGULAR)

    # Kill all processes holding our ports (port-based, no broad process-name kills)
    log_step "Killing processes on project ports..."
    for port in "${all_ports[@]}"; do
        if is_windows; then
            kill_port_windows_ps "$port"
        fi
        for pid in $(get_pids_on_port "$port"); do
            [[ -z "$pid" ]] && continue
            log_info "  Killing PID $pid on port $port"
            if is_windows; then
                taskkill //F //PID "$pid" >/dev/null 2>&1 || true
            else
                kill -9 "$pid" 2>/dev/null || true
            fi
        done
    done

    # Stop MLflow Docker container
    log_step "Stopping MLflow..."
    _docker_compose stop mlflow 2>/dev/null || true

    # Kill any saved PIDs that may not have had an active port
    if [[ -d "$PIDS_DIR" ]]; then
        for pid_file in "$PIDS_DIR"/*.pid; do
            [[ -f "$pid_file" ]] || continue
            local saved_pid
            saved_pid=$(cat "$pid_file" 2>/dev/null)
            if [[ -n "$saved_pid" ]]; then
                log_info "  Killing saved PID $saved_pid ($(basename "$pid_file" .pid))"
                if is_windows; then
                    taskkill //F //PID "$saved_pid" >/dev/null 2>&1 || true
                else
                    kill -9 "$saved_pid" 2>/dev/null || true
                fi
            fi
        done
        rm -rf "$PIDS_DIR"
    fi

    # Stop Docker containers
    log_step "Stopping Docker containers..."
    _docker_compose stop app-db 2>/dev/null || docker stop querywise-postgres 2>/dev/null || true
    _docker_compose stop redis 2>/dev/null || docker stop querywise-redis 2>/dev/null || true

    echo ""
    log_info "Clean complete!"
}

# =============================================================================
# Helpers
# =============================================================================

# Ensure dev.pids/ is in .gitignore (idempotent)
_ensure_gitignore_entry() {
    local gitignore="$SCRIPT_DIR/.gitignore"
    local entry="dev.pids/"
    if [[ -f "$gitignore" ]] && grep -qF "$entry" "$gitignore"; then
        return 0
    fi
    echo "" >> "$gitignore"
    echo "# Dev process PID tracking" >> "$gitignore"
    echo "$entry" >> "$gitignore"
    log_info "Added $entry to .gitignore"
}

# =============================================================================
# Usage
# =============================================================================

show_usage() {
    echo "QueryWise Native Development Script"
    echo ""
    echo "Usage: $0 <command> [service]"
    echo ""
    echo "Commands:"
    echo "  start              Start all services"
    echo "  stop               Stop all services"
    echo "  restart [service]  Restart all (or a specific) service"
    echo "  status             Show running processes/ports"
    echo "  logs               Tail backend logs"
    echo "  db                 Toggle PostgreSQL (Docker)"
    echo "  clean              Kill all dev processes and clean up"
    echo ""
    echo "Services (for restart):"
    echo "  backend  frontend  angular  redis  mlflow"
    echo ""
    echo "Ports:"
    printf "  %-22s port %s\n" "PostgreSQL (Docker)"  "$PORT_DB"
    printf "  %-22s port %s\n" "Redis (Docker)"       "$PORT_REDIS"
    printf "  %-22s port %s\n" "MLflow (Docker)"      "$PORT_MLFLOW"
    printf "  %-22s port %s\n" "Ollama (system)"      "$PORT_OLLAMA"
    printf "  %-22s port %s\n" "Backend (uvicorn)"    "$PORT_BACKEND"
    printf "  %-22s port %s\n" "Frontend (Vite)"      "$PORT_FRONTEND"
    printf "  %-22s port %s\n" "Angular Test"         "$PORT_ANGULAR"
}

# =============================================================================
# Entry Point
# =============================================================================

case "${1:-}" in
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart "${2:-}"
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    db)
        cmd_db
        ;;
    clean)
        cmd_clean
        ;;
    -h|--help|help)
        show_usage
        ;;
    "")
        show_usage
        ;;
    *)
        log_error "Unknown command: $1"
        echo ""
        show_usage
        exit 1
        ;;
esac