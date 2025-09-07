import asyncio
from fastapi import APIRouter
from collections import defaultdict
import database as db
import server_config
import system_manager as sm
from api.models import APIResponse
from api.dependencies import verify_token
from fastapi import Depends

router = APIRouter(prefix="/servers", tags=["Servers"])

@router.get("/status", response_model=APIResponse)
async def get_all_servers_status():
    servers = server_config.get_servers()
    
    stats_tasks = {ip: sm.get_server_stats(ip) for ip in servers}
    ub_counts_tasks = {ip: db.get_userbots_by_server_ip(ip) for ip in servers}
    
    stats_results = await asyncio.gather(*stats_tasks.values())
    ub_counts_results = await asyncio.gather(*ub_counts_tasks.values())
    
    stats_map = dict(zip(stats_tasks.keys(), stats_results))
    ub_counts_map = {ip: len(ubs) for ip, ubs in zip(ub_counts_tasks.keys(), ub_counts_results)}
    
    servers_status_list = []
    
    sorted_servers = sorted(servers.items(), key=lambda item: item[1].get('code', item[0]))
    
    for ip, details in sorted_servers:
        if ip == sm.LOCAL_IP:
            continue
            
        stats = stats_map.get(ip, {})
        
        server_info = {
            "code": details.get('code', 'N/A'),
            "location": f"{details.get('country', 'N/A')}, {details.get('city', 'N/A')}",
            "flag": details.get('flag', '🏳️'),
            "status": details.get('status', 'false'),
            "cpu_usage": stats.get('cpu_usage', 'N/A'),
            "disk_usage": stats.get('disk_percent', 'N/A'),
            "slots": {
                "used": ub_counts_map.get(ip, 0),
                "total": details.get('slots', 0)
            }
        }
        servers_status_list.append(server_info)
        
    return APIResponse(data={"servers": servers_status_list})