document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const elStarsTotal = document.getElementById('stars-total');
    const elStarsDelta = document.getElementById('stars-delta');
    const elStarsDeltaContainer = document.getElementById('stars-delta-container');
    const elDownloadsTotal = document.getElementById('downloads-total');
    const elDownloadsDelta = document.getElementById('downloads-delta');
    const elDownloadsDeltaContainer = document.getElementById('downloads-delta-container');
    const elUvTotal = document.getElementById('uv-total');
    const elUvNew = document.getElementById('uv-new');
    const elUvOld = document.getElementById('uv-old');
    const elUvYesterday = document.getElementById('uv-yesterday');
    
    const elBadgeGithub = document.getElementById('badge-github');
    const elBadgeBaidu = document.getElementById('badge-baidu');
    const elLastUpdateTime = document.getElementById('last-update-time');
    const elBtnRefresh = document.getElementById('btn-refresh');
    const elBtnSettings = document.getElementById('btn-settings');
    const elWarmupBanner = document.getElementById('warmup-banner');
    const elErrorBanner = document.getElementById('error-banner');
    const elErrorMessage = document.getElementById('error-message');
    
    // Status Indicators
    const elStatusGithubStars = document.getElementById('status-github-stars');
    const elStatusGithubDownloads = document.getElementById('status-github-downloads');
    const elStatusBaiduUv = document.getElementById('status-baidu-uv');
    
    // Modal Elements
    const elSettingsModal = document.getElementById('settings-modal');
    const elBtnCloseModal = document.getElementById('btn-close-modal');
    const elBtnCancelConfig = document.getElementById('btn-cancel-config');
    const elConfigForm = document.getElementById('config-form');

    
    // Form Inputs & Version Elements
    const inputGithubToken = document.getElementById('github_token');
    const inputMsiVersion = document.getElementById('msi_version');
    const inputBaiduSiteId = document.getElementById('baidu_site_id');
    const elMsiVersionTag = document.getElementById('msi-version-tag');

    
    // Chart Instance variable
    let uvChart = null;
    let isFetching = false;

    // Geo Ranking state and elements
    let geoData = { districts: { today: [], yesterday: [] }, countries: { today: [], yesterday: [] } };
    let currentGeoTab = 'today';
    const elGeoList = document.getElementById('geo-list');
    const elBtnGeoToday = document.getElementById('btn-geo-today');
    const elBtnGeoYesterday = document.getElementById('btn-geo-yesterday');

    // New Visitor Geo & All Visitor Country analysis state and elements
    let newGeoChart = null;
    let countryChart = null;
    let retentionChart = null;
    let newGeoData = { districts: { today: [], yesterday: [] }, countries: { today: [], yesterday: [] } };
    let countryData = { districts: { today: [], yesterday: [] }, countries: { today: [], yesterday: [] } };
    let currentNewGeoTab = 'today';
    let currentCountryTab = 'today';
    let traceData = { today: [], yesterday: [] };
    let currentTraceTab = 'today';

    const elBtnNewGeoToday = document.getElementById('btn-newgeo-today');
    const elBtnNewGeoYesterday = document.getElementById('btn-newgeo-yesterday');
    const elBtnCountryToday = document.getElementById('btn-country-today');
    const elBtnCountryYesterday = document.getElementById('btn-country-yesterday');
    const elCountryList = document.getElementById('country-list');
    const elBtnTraceToday = document.getElementById('btn-trace-today');
    const elBtnTraceYesterday = document.getElementById('btn-trace-yesterday');
    const elTraceTitle = document.getElementById('trace-title');
    const elTraceSubtitle = document.getElementById('trace-subtitle');

    // Chart Tab State and Elements
    let currentChartTab = '7d';
    let baiduMetrics = null;

    const elChartTitle = document.getElementById('chart-title');
    const elChartSubtitle = document.getElementById('chart-subtitle');
    const elBtnChart7d = document.getElementById('btn-chart-7d');
    const elBtnChart24h = document.getElementById('btn-chart-24h');
    const elChartLegend = document.getElementById('chart-legend');
    const elTraceCountLabel = document.getElementById('trace-count-label');

    // Retention DOM Elements
    const elRetentionTotal = document.getElementById('retention-total-visitors');
    const elRetentionCnt1 = document.getElementById('retention-cnt-1');
    const elRetentionRatio1 = document.getElementById('retention-ratio-1');
    const elRetentionCnt2 = document.getElementById('retention-cnt-2');
    const elRetentionRatio2 = document.getElementById('retention-ratio-2');
    const elRetentionCnt3 = document.getElementById('retention-cnt-3');
    const elRetentionRatio3 = document.getElementById('retention-ratio-3');
    const elRetentionCnt5 = document.getElementById('retention-cnt-5');
    const elRetentionRatio5 = document.getElementById('retention-ratio-5');
    const elRetentionCnt9 = document.getElementById('retention-cnt-9');
    const elRetentionRatio9 = document.getElementById('retention-ratio-9');
    const elRetentionCnt15 = document.getElementById('retention-cnt-15');
    const elRetentionRatio15 = document.getElementById('retention-ratio-15');
    const elRetentionCnt30 = document.getElementById('retention-cnt-30');
    const elRetentionRatio30 = document.getElementById('retention-ratio-30');

    // Initialize the Chart
    function initChart() {
        const ctx = document.getElementById('uvTrendChart').getContext('2d');
        
        // Generate beautiful gradient background for today's line
        const pinkGradient = ctx.createLinearGradient(0, 0, 0, 300);
        pinkGradient.addColorStop(0, 'rgba(255, 117, 140, 0.4)');
        pinkGradient.addColorStop(1, 'rgba(255, 117, 140, 0.0)');
        
        const hoursLabels = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`);

        uvChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: []
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false // We use our custom legend in HTML
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: '#171923',
                        titleColor: '#f3f4f6',
                        titleFont: {
                            family: 'Outfit',
                            size: 13,
                            weight: 'bold'
                        },
                        bodyColor: '#e5e7eb',
                        bodyFont: {
                            family: 'Inter',
                            size: 12
                        },
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1,
                        padding: 10,
                        displayColors: true,
                        callbacks: {
                            labelColor: function(context) {
                                return {
                                    borderColor: context.dataset.borderColor,
                                    backgroundColor: context.dataset.borderColor
                                };
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: {
                            color: 'rgba(255, 255, 255, 0.03)',
                            drawBorder: false
                        },
                        ticks: {
                            color: '#9ca3af',
                            font: {
                                size: 10,
                                family: 'monospace'
                            }
                        }
                    },
                    y: {
                        grid: {
                            color: 'rgba(255, 255, 255, 0.03)',
                            drawBorder: false
                        },
                        ticks: {
                            color: '#9ca3af',
                            font: {
                                size: 10,
                                family: 'monospace'
                            },
                            precision: 0
                        },
                        min: 0
                    }
                }
            }
        });
        // Initialize All Visitor Country Chart (Doughnut Chart)
        const countryCtx = document.getElementById('countryChart').getContext('2d');
        countryChart = new Chart(countryCtx, {
            type: 'doughnut',
            data: {
                labels: [],
                datasets: [{
                    data: [],
                    backgroundColor: [
                        '#ff758c', // 中国
                        '#00f2fe', // 美国
                        '#a259ff', // 日本
                        '#f59e0b', // 新加坡
                        '#10b981', // 德国
                        '#3b82f6', // 加拿大
                        '#9ca3af'  // 英国 / 其他
                    ],
                    borderWidth: 1.5,
                    borderColor: '#12141d',
                    hoverOffset: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '70%',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: '#171923',
                        titleColor: '#f3f4f6',
                        bodyColor: '#e5e7eb',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1,
                        callbacks: {
                            label: function(context) {
                                const label = context.label || '';
                                const val = context.raw || 0;
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
                                return ` ${label}: ${val} UV (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });

        // Initialize Retention Chart (Bar Chart)
        const retentionElem = document.getElementById('retentionChart');
        if (retentionElem) {
            const retentionCtx = retentionElem.getContext('2d');
            retentionChart = new Chart(retentionCtx, {
                type: 'bar',
                data: {
                    labels: ['1天', '2天', '3~4天', '5~8天', '9~14天', '15~29天', '≥30天'],
                    datasets: [{
                        label: '活跃留存人数',
                        data: [0, 0, 0, 0, 0, 0, 0],
                        backgroundColor: [
                            'rgba(16, 185, 129, 0.75)',
                            'rgba(59, 130, 246, 0.75)',
                            'rgba(255, 117, 140, 0.75)',
                            'rgba(0, 242, 254, 0.75)',
                            'rgba(236, 72, 153, 0.75)',
                            'rgba(162, 89, 255, 0.75)',
                            'rgba(255, 184, 0, 0.75)'
                        ],
                        borderColor: [
                            '#10b981',
                            '#3b82f6',
                            '#ff758c',
                            '#00f2fe',
                            '#ec4899',
                            '#a259ff',
                            '#ffb800'
                        ],
                        borderWidth: 1.5,
                        borderRadius: 8,
                        barThickness: 32
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: '#171923',
                            titleColor: '#f3f4f6',
                            bodyColor: '#e5e7eb',
                            borderColor: 'rgba(255,255,255,0.08)',
                            borderWidth: 1,
                            callbacks: {
                                label: function(context) {
                                    const val = context.raw || 0;
                                    return ` 留存人数: ${val} 人`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { display: false },
                            ticks: { color: 'rgba(255, 255, 255, 0.7)', font: { size: 11 } }
                        },
                        y: {
                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                            ticks: { color: 'rgba(255, 255, 255, 0.4)', precision: 0 },
                            beginAtZero: true
                        }
                    }
                }
            });
        }
    }

    // Dynamic Chart rendering (14-day daily UV vs 24h hourly UV)
    function updateChartData() {
        if (!uvChart || !baiduMetrics) return;

        const ctx = document.getElementById('uvTrendChart').getContext('2d');
        const pinkGradient = ctx.createLinearGradient(0, 0, 0, 300);
        pinkGradient.addColorStop(0, 'rgba(255, 117, 140, 0.4)');
        pinkGradient.addColorStop(1, 'rgba(255, 117, 140, 0.0)');

        const cyanGradient = ctx.createLinearGradient(0, 0, 0, 300);
        cyanGradient.addColorStop(0, 'rgba(0, 242, 254, 0.3)');
        cyanGradient.addColorStop(1, 'rgba(0, 242, 254, 0.0)');

        const purpleGradient = ctx.createLinearGradient(0, 0, 0, 300);
        purpleGradient.addColorStop(0, 'rgba(162, 89, 255, 0.3)');
        purpleGradient.addColorStop(1, 'rgba(162, 89, 255, 0.0)');

        let tabChanged = false;
        if (uvChart._activeTab !== currentChartTab) {
            uvChart._activeTab = currentChartTab;
            tabChanged = true;
        }

        if (currentChartTab === '7d') {
            if (elChartTitle) elChartTitle.textContent = '最近两周每日访客变化曲线 (UV)';
            if (elChartSubtitle) elChartSubtitle.textContent = '过去14天每日独立访客数量 (UV) 变化趋势与新老访客分布';

            if (elChartLegend) {
                elChartLegend.innerHTML = `
                    <div class="legend-item">
                        <span class="legend-color legend-today"></span>
                        <span>总访客 (UV)</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-color legend-new"></span>
                        <span>新访客 (UV)</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-color legend-old"></span>
                        <span>老访客 (UV)</span>
                    </div>
                `;
            }

            const trend = baiduMetrics.daily_uv_trend || [];
            const labels = trend.map(item => item.label);
            const totalData = trend.map(item => item.total_uv);
            const newData = trend.map(item => item.new_uv);
            const oldData = trend.map(item => item.old_uv);

            uvChart.data.labels = labels;

            if (tabChanged || !uvChart.data.datasets || uvChart.data.datasets.length !== 3) {
                uvChart.data.datasets = [
                    {
                        label: '总访客 (UV)',
                        data: totalData,
                        borderColor: '#ff758c',
                        borderWidth: 3,
                        pointBackgroundColor: '#ff758c',
                        pointBorderColor: 'rgba(255, 255, 255, 0.3)',
                        pointBorderWidth: 1,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointHoverBackgroundColor: '#ffffff',
                        pointHoverBorderColor: '#ff758c',
                        pointHoverBorderWidth: 3,
                        backgroundColor: pinkGradient,
                        fill: true,
                        tension: 0.35
                    },
                    {
                        label: '新访客 (UV)',
                        data: newData,
                        borderColor: '#00f2fe',
                        borderWidth: 2,
                        pointBackgroundColor: '#00f2fe',
                        pointBorderColor: 'rgba(255, 255, 255, 0.3)',
                        pointBorderWidth: 1,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        pointHoverBackgroundColor: '#ffffff',
                        pointHoverBorderColor: '#00f2fe',
                        pointHoverBorderWidth: 2,
                        backgroundColor: cyanGradient,
                        fill: false,
                        tension: 0.35
                    },
                    {
                        label: '老访客 (UV)',
                        data: oldData,
                        borderColor: '#a259ff',
                        borderWidth: 2,
                        borderDash: [4, 4],
                        pointBackgroundColor: '#a259ff',
                        pointBorderColor: 'transparent',
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        pointHoverBackgroundColor: '#ffffff',
                        pointHoverBorderColor: '#a259ff',
                        pointHoverBorderWidth: 2,
                        backgroundColor: purpleGradient,
                        fill: false,
                        tension: 0.35
                    }
                ];
                uvChart.update();
            } else {
                uvChart.data.datasets[0].data = totalData;
                uvChart.data.datasets[1].data = newData;
                uvChart.data.datasets[2].data = oldData;
                uvChart.update('none');
            }
        } else {
            if (elChartTitle) elChartTitle.textContent = '今日访客分时变化曲线 (UV)';
            if (elChartSubtitle) elChartSubtitle.textContent = '每小时的独立访客数量，对比昨日同一时段变化';

            if (elChartLegend) {
                elChartLegend.innerHTML = `
                    <div class="legend-item">
                        <span class="legend-color legend-today"></span>
                        <span>今日 (UV)</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-color legend-yesterday"></span>
                        <span>昨日 (UV)</span>
                    </div>
                `;
            }

            const hoursLabels = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`);
            uvChart.data.labels = hoursLabels;
            const tData = baiduMetrics.today_hourly_uv || Array(24).fill(0);
            const yData = baiduMetrics.yesterday_hourly_uv || Array(24).fill(0);

            if (tabChanged || !uvChart.data.datasets || uvChart.data.datasets.length !== 2) {
                uvChart.data.datasets = [
                    {
                        label: '今日 (UV)',
                        data: tData,
                        borderColor: '#ff758c',
                        borderWidth: 3,
                        pointBackgroundColor: '#ff758c',
                        pointBorderColor: 'rgba(255, 255, 255, 0.3)',
                        pointBorderWidth: 1,
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointHoverBackgroundColor: '#ffffff',
                        pointHoverBorderColor: '#ff758c',
                        pointHoverBorderWidth: 3,
                        backgroundColor: pinkGradient,
                        fill: true,
                        tension: 0.35
                    },
                    {
                        label: '昨日 (UV)',
                        data: yData,
                        borderColor: 'rgba(255, 255, 255, 0.18)',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        pointBackgroundColor: 'rgba(255, 255, 255, 0.2)',
                        pointBorderColor: 'transparent',
                        pointRadius: 2,
                        pointHoverRadius: 4,
                        fill: false,
                        tension: 0.35
                    }
                ];
                uvChart.update();
            } else {
                uvChart.data.datasets[0].data = tData;
                uvChart.data.datasets[1].data = yData;
                uvChart.update('none');
            }
        }
    }



    // Modal management
    function openModal() {
        elSettingsModal.classList.remove('hidden');
        // Fetch current masked configurations
        fetch('/api/config')
            .then(res => res.json())
            .then(data => {
                inputGithubToken.value = data.github_token;
                if (inputMsiVersion) inputMsiVersion.value = data.msi_version || 'v1.1.5';
                inputBaiduSiteId.value = data.baidu_site_id;
            })
            .catch(err => {
                console.error("Failed to load configs:", err);
            });
    }

    function closeModal() {
        elSettingsModal.classList.add('hidden');
    }

    elBtnSettings.addEventListener('click', openModal);
    elBtnCloseModal.addEventListener('click', closeModal);
    elBtnCancelConfig.addEventListener('click', closeModal);

    // Save configurations
    elConfigForm.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const payload = {
            github_token: inputGithubToken.value.trim(),
            msi_version: inputMsiVersion ? inputMsiVersion.value.trim() : '',
            baidu_site_id: inputBaiduSiteId.value.trim()
        };

        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success') {
                closeModal();
                fetchMetrics(); // Fetch metrics immediately with new config
            } else {
                alert("保存配置失败：" + data.message);
            }
        })
        .catch(err => {
            console.error("Save config error:", err);
            alert("无法保存配置，请检查后端网络连接。");
        });
    });

    // Helper to format deltas
    function updateDeltaBadge(elContainer, elText, val) {
        elText.textContent = `+${val}`;
        if (val > 0) {
            elContainer.className = 'delta-badge delta-positive';
        } else {
            elText.textContent = '0';
            elContainer.className = 'delta-badge delta-neutral';
        }
    }

    // Helper to update status indicators
    function setStatus(elDot, status) {
        elDot.className = 'api-status';
        if (status === 'online') {
            elDot.classList.add('status-online');
            elDot.title = "接口在线（实时数据）";
        } else if (status === 'cached') {
            elDot.classList.add('status-cached');
            elDot.title = "数据库缓存（API受限，显示历史数据）";
        } else if (status === 'unconfigured') {
            elDot.classList.add('status-unconfigured');
            elDot.title = "未配置相关凭证";
        } else {
            elDot.classList.add('status-error');
            elDot.title = "同步异常";
        }
    }

    // Helper to render geographical visitor list
    function renderGeoList() {
        if (!elGeoList) return;
        const list = (geoData.districts && geoData.districts[currentGeoTab]) || [];
        if (list.length === 0) {
            elGeoList.innerHTML = '<div class="empty-state">暂无地域数据</div>';
            return;
        }
        
        // Sort districts by total visitor value descending for the general ranking list
        const sortedList = [...list].sort((a, b) => b.value - a.value);
        const maxVal = Math.max(...sortedList.map(x => x.value), 1);
        
        elGeoList.innerHTML = sortedList.map(item => {
            const pct = (item.value / maxVal) * 100;
            return `
                <div class="geo-item">
                    <div class="geo-item-info">
                        <span class="geo-name">${item.name}</span>
                        <span class="geo-value">${item.value} UV</span>
                    </div>
                    <div class="geo-bar-bg">
                        <div class="geo-bar-fill" style="width: ${pct}%"></div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Helper to get country flag emoji
    function getCountryFlag(name) {
        const flags = {
            "中国": "🇨🇳",
            "美国": "🇺🇸",
            "日本": "🇯🇵",
            "新加坡": "🇸🇬",
            "德国": "🇩🇪",
            "加拿大": "🇨🇦",
            "英国": "🇬🇧",
            "荷兰": "🇳🇱",
            "澳大利亚": "🇦🇺",
            "法国": "🇫🇷",
            "韩国": "🇰🇷",
            "China": "🇨🇳",
            "United States": "🇺🇸",
            "Japan": "🇯🇵",
            "Singapore": "🇸🇬",
            "Germany": "🇩🇪",
            "Canada": "🇨🇦",
            "United Kingdom": "🇬🇧",
            "Netherlands": "🇳🇱"
        };
        return flags[name] || "🌐";
    }

    const elHourlyGeoGrid = document.getElementById('hourly-geo-grid');

    // Helper to render 24-hour chronological new visitor geography rectangle cards (flicker-free update)
    function renderHourlyNewGeoGrid() {
        if (!elHourlyGeoGrid) return;
        const currentHour = new Date().getHours();
        const tabKey = currentNewGeoTab;
        const isToday = (tabKey === 'today');

        let hourlyList = (newGeoData.hourly_new_geo && newGeoData.hourly_new_geo[tabKey]) || [];

        // Dynamic fallback if hourlyList is missing or incomplete
        if (!hourlyList || hourlyList.length < 24) {
            hourlyList = Array.from({ length: 24 }, () => ({ status: 'empty', total_uv: 0, new_uv: 0, old_uv: 0, regions: [] }));
        }

        const existingCards = elHourlyGeoGrid.querySelectorAll('.hourly-rect-card');
        const isFirstRender = (existingCards.length !== 24);

        if (isFirstRender) {
            let html = '';
            for (let h = 0; h < 24; h++) {
                const timeLabel = `${String(h).padStart(2, '0')}:00`;
                html += `
                    <div class="hourly-rect-card" data-hour="${h}">
                        <div class="rect-card-header">
                            <span class="rect-time">${timeLabel}</span>
                            <div class="rect-header-badge-wrap"></div>
                        </div>
                        <div class="rect-card-body"></div>
                    </div>
                `;
            }
            elHourlyGeoGrid.innerHTML = html;
        }

        const cards = elHourlyGeoGrid.querySelectorAll('.hourly-rect-card');
        cards.forEach((card, h) => {
            const hourObj = hourlyList[h] || {};
            const isFuture = (isToday && h > currentHour);
            const isActiveHour = (isToday && h === currentHour);
            
            // Support object structure { total_uv, new_uv, old_uv, regions } or array structure
            let newUv = 0, oldUv = 0, totalUv = 0, regions = [];
            if (Array.isArray(hourObj)) {
                regions = hourObj;
                totalUv = regions.reduce((sum, item) => sum + (item.count || 0), 0);
                newUv = totalUv;
            } else {
                newUv = hourObj.new_uv || 0;
                oldUv = hourObj.old_uv || 0;
                totalUv = hourObj.total_uv || (newUv + oldUv);
                regions = hourObj.regions || [];
            }

            // Update card class list
            card.classList.toggle('future', isFuture);
            card.classList.toggle('active-hour', isActiveHour);

            // Body HTML
            let bodyHtml = '';
            if (isFuture) {
                bodyHtml = `<div class="rect-empty-msg">未到时间</div>`;
            } else if (totalUv === 0 || regions.length === 0) {
                bodyHtml = `<div class="rect-empty-msg">无访客</div>`;
            } else {
                bodyHtml = regions.slice(0, 3).map(item => {
                    const foreignBadge = item.is_foreign ? `<span class="foreign-tag">国外</span>` : '';
                    const newCnt = item.new_count || 0;
                    const oldCnt = item.old_count || 0;
                    let countBadges = '';
                    if (newCnt > 0 && oldCnt > 0) {
                        countBadges = `<span class="rect-region-count count-new">+${newCnt}新</span><span class="rect-region-count count-old">+${oldCnt}老</span>`;
                    } else if (newCnt > 0) {
                        countBadges = `<span class="rect-region-count count-new">+${newCnt}新</span>`;
                    } else if (oldCnt > 0) {
                        countBadges = `<span class="rect-region-count count-old">+${oldCnt}老</span>`;
                    } else {
                        countBadges = `<span class="rect-region-count">+${item.count}</span>`;
                    }

                    return `
                        <div class="rect-region-row">
                            <span class="rect-region-name" title="${item.name}">${item.name}${foreignBadge}</span>
                            <div class="rect-region-count-group">${countBadges}</div>
                        </div>
                    `;
                }).join('');
            }

            // Header Badge HTML
            let headerBadgeHtml = '';
            if (isFuture) {
                headerBadgeHtml = `<span class="rect-total-badge">-</span>`;
            } else if (totalUv === 0) {
                headerBadgeHtml = `<span class="rect-total-badge">0</span>`;
            } else {
                let badges = '';
                if (newUv > 0) badges += `<span class="rect-pill pill-new" title="新客">+${newUv}新</span>`;
                if (oldUv > 0) badges += `<span class="rect-pill pill-old" title="老客">+${oldUv}老</span>`;
                if (!badges) badges = `<span class="rect-total-badge has-data">${totalUv}人</span>`;
                headerBadgeHtml = `<div class="rect-badge-group">${badges}</div>`;
            }

            const badgeWrap = card.querySelector('.rect-header-badge-wrap');
            const cardBody = card.querySelector('.rect-card-body');

            if (badgeWrap && badgeWrap.innerHTML !== headerBadgeHtml) {
                badgeWrap.innerHTML = headerBadgeHtml;
            }
            if (cardBody && cardBody.innerHTML !== bodyHtml) {
                cardBody.innerHTML = bodyHtml;
            }
        });
    }

    // Helper to render all visitor country chart & details list
    function renderCountryChartAndList() {
        if (!countryChart || !elCountryList) return;
        const list = (countryData.countries && countryData.countries[currentCountryTab]) || [];
        if (list.length === 0) {
            countryChart.data.labels = [];
            countryChart.data.datasets[0].data = [];
            countryChart.update();
            elCountryList.innerHTML = '<div class="empty-state">暂无国家数据</div>';
            return;
        }

        // Color mapping to keep doughnut sectors and list progress bars visually consistent
        const COUNTRY_COLORS = {
            "中国": "#ff758c",
            "美国": "#00f2fe",
            "日本": "#a259ff",
            "新加坡": "#f59e0b",
            "德国": "#10b981",
            "加拿大": "#3b82f6",
            "其他": "#9ca3af"
        };
        const DEFAULT_COLORS = ["#ff758c", "#00f2fe", "#a259ff", "#f59e0b", "#10b981", "#3b82f6", "#9ca3af"];

        const datasetColors = list.map((item, idx) => {
            return COUNTRY_COLORS[item.name] || DEFAULT_COLORS[idx % DEFAULT_COLORS.length];
        });

        // 1. Update doughnut chart (all entries)
        countryChart.data.labels = list.map(x => x.name);
        countryChart.data.datasets[0].data = list.map(x => x.value);
        countryChart.data.datasets[0].backgroundColor = datasetColors;
        countryChart.update();

        // 2. Update details list
        const maxVal = Math.max(...list.map(x => x.value), 1);
        const totalVal = list.reduce((a, b) => a + b.value, 0);

        elCountryList.innerHTML = list.map((item, idx) => {
            const pct = (item.value / maxVal) * 100;
            const share = totalVal > 0 ? ((item.value / totalVal) * 100).toFixed(1) : 0;
            const flag = getCountryFlag(item.name);
            const color = datasetColors[idx];
            return `
                <div class="country-item">
                    <div class="country-item-info">
                        <span class="country-name-group">
                            <span class="country-flag" title="${item.name}">${flag}</span>
                            <span class="country-name">${item.name}</span>
                        </span>
                        <span class="country-value" style="color: ${color}; font-weight: 700;">${item.value} UV (${share}%)</span>
                    </div>
                    <div class="country-bar-bg">
                        <div class="country-bar-fill" style="width: ${pct}%; background: ${color}; box-shadow: 0 0 8px ${color}80;"></div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // Helper to render Today's Visitors Historical Trace Table
    const elTodayVisitorsTbody = document.getElementById('today-visitors-tbody');
    const elTodayVisitorsCount = document.getElementById('today-visitors-count');

    function getDaysIcon(days) {
        if (days >= 30) return '👑';
        if (days >= 15) return '⭐';
        if (days >= 9)  return '🚀';
        if (days >= 5)  return '⚡';
        if (days >= 3)  return '🔥';
        if (days === 2) return '🌿';
        return '🌱';
    }

    function renderTraceTable() {
        if (!elTodayVisitorsTbody) return;
        const list = traceData[currentTraceTab] || [];
        
        if (elTodayVisitorsCount) {
            elTodayVisitorsCount.textContent = list.length;
        }

        const isTodayTab = (currentTraceTab === 'today');
        if (elTraceTitle) elTraceTitle.textContent = isTodayTab ? '今日访客历史访问轨迹表' : '昨日访客历史访问轨迹表';
        if (elTraceSubtitle) elTraceSubtitle.textContent = isTodayTab 
            ? '全量追踪今日所有来访访客的地区归属、IP地址、历史累计天数及详细访问日期清单'
            : '全量追踪昨日所有来访访客的地区归属、IP地址、历史累计天数及详细访问日期清单';
        if (elTraceCountLabel) elTraceCountLabel.textContent = isTodayTab ? '今日访客数: ' : '昨日访客数: ';

        if (list.length === 0) {
            elTodayVisitorsTbody.innerHTML = `<tr><td colspan="5" class="empty-state">${isTodayTab ? '今日' : '昨日'}暂无访客数据</td></tr>`;
            return;
        }

        const now = new Date();
        const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
        const yesterday = new Date(now.getTime() - 86400000);
        const yesterdayStr = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`;
        
        const highlightTargetDate = isTodayTab ? todayStr : yesterdayStr;
        const highlightLabel = isTodayTab ? ' (今日)' : ' (昨日)';

        elTodayVisitorsTbody.innerHTML = list.map((item) => {
            const flag = getCountryFlag(item.area);
            const foreignBadge = item.is_foreign ? `<span class="foreign-tag">国外</span>` : '';
            
            let typePill = '';
            if (item.is_reactivated) {
                typePill = `<span class="rect-pill pill-reactivated" title="沉寂${item.gap_days || 3}天后重返">+1返</span>`;
            } else if (item.visitor_type === "新访客") {
                typePill = `<span class="rect-pill pill-new">+1新</span>`;
            } else {
                typePill = `<span class="rect-pill pill-old">+1老</span>`;
            }

            const datesToUse = item.dates || [];
            const daysCount = item.days_count || datesToUse.length || 1;
            const icon = getDaysIcon(daysCount);
            
            let badgeClass = 'days-badge';
            if (daysCount === 2 || daysCount === 3) {
                badgeClass += ' yellow';
            } else if (daysCount >= 4) {
                badgeClass += ' highlight';
            }
            const daysBadgeHtml = `<span class="${badgeClass}">${icon} ${daysCount} 天</span>`;
            
            let datesHtml = '';
            if (datesToUse.length >= 13 && item.first_date && item.last_date) {
                const firstShort = String(item.first_date || '').slice(0, 10).slice(5);
                const lastShort = String(item.last_date || '').slice(0, 10).slice(5);
                datesHtml = `<span class="date-chip streak-full">🔥 ${firstShort} 至 ${lastShort} (${datesToUse.length}天全勤)</span>`;
            } else {
                datesHtml = `<div class="date-chips-container">` + datesToUse.map(rawD => {
                    const cleanD = String(rawD || '').slice(0, 10);
                    if (!cleanD || cleanD.length < 10) return '';
                    const shortDate = cleanD.slice(5);
                    const isCur = (cleanD === highlightTargetDate);
                    return `<span class="date-chip ${isCur ? 'today-chip' : ''}">${shortDate}${isCur ? highlightLabel : ''}</span>`;
                }).filter(Boolean).join('') + `</div>`;
            }

            return `
                <tr>
                    <td>
                        <span style="font-weight: 600;">${flag} ${item.area}${foreignBadge}</span>
                    </td>
                    <td>
                        <code class="ip-code">${item.ip}</code>
                    </td>
                    <td>${typePill}</td>
                    <td>${daysBadgeHtml}</td>
                    <td>${datesHtml}</td>
                </tr>
            `;
        }).join('');
    }

    // Bind main UV chart tab toggles
    if (elBtnChart7d && elBtnChart24h) {
        elBtnChart7d.addEventListener('click', () => {
            currentChartTab = '7d';
            elBtnChart7d.classList.add('active');
            elBtnChart24h.classList.remove('active');
            updateChartData();
        });
        elBtnChart24h.addEventListener('click', () => {
            currentChartTab = '24h';
            elBtnChart24h.classList.add('active');
            elBtnChart7d.classList.remove('active');
            updateChartData();
        });
    }

    // Bind trace tabs toggles
    if (elBtnTraceToday && elBtnTraceYesterday) {
        elBtnTraceToday.addEventListener('click', () => {
            currentTraceTab = 'today';
            elBtnTraceToday.classList.add('active');
            elBtnTraceYesterday.classList.remove('active');
            renderTraceTable();
        });
        elBtnTraceYesterday.addEventListener('click', () => {
            currentTraceTab = 'yesterday';
            elBtnTraceYesterday.classList.add('active');
            elBtnTraceToday.classList.remove('active');
            renderTraceTable();
        });
    }

    // Bind geo tabs toggles
    if (elBtnGeoToday && elBtnGeoYesterday) {
        elBtnGeoToday.addEventListener('click', () => {
            currentGeoTab = 'today';
            elBtnGeoToday.classList.add('active');
            elBtnGeoYesterday.classList.remove('active');
            renderGeoList();
        });
        
        elBtnGeoYesterday.addEventListener('click', () => {
            currentGeoTab = 'yesterday';
            elBtnGeoYesterday.classList.add('active');
            elBtnGeoToday.classList.remove('active');
            renderGeoList();
        });
    }

    // Bind new geo tabs toggles
    if (elBtnNewGeoToday && elBtnNewGeoYesterday) {
        elBtnNewGeoToday.addEventListener('click', () => {
            currentNewGeoTab = 'today';
            elBtnNewGeoToday.classList.add('active');
            elBtnNewGeoYesterday.classList.remove('active');
            renderHourlyNewGeoGrid();
        });
        elBtnNewGeoYesterday.addEventListener('click', () => {
            currentNewGeoTab = 'yesterday';
            elBtnNewGeoYesterday.classList.add('active');
            elBtnNewGeoToday.classList.remove('active');
            renderHourlyNewGeoGrid();
        });
    }

    // Bind country tabs toggles
    if (elBtnCountryToday && elBtnCountryYesterday) {
        elBtnCountryToday.addEventListener('click', () => {
            currentCountryTab = 'today';
            elBtnCountryToday.classList.add('active');
            elBtnCountryYesterday.classList.remove('active');
            renderCountryChartAndList();
        });
        elBtnCountryYesterday.addEventListener('click', () => {
            currentCountryTab = 'yesterday';
            elBtnCountryYesterday.classList.add('active');
            elBtnCountryToday.classList.remove('active');
            renderCountryChartAndList();
        });
    }

    // Fetch metric details
    function fetchMetrics() {
        if (isFetching) return;
        isFetching = true;
        
        // Add spin animation to manual refresh icon
        const syncIcon = elBtnRefresh.querySelector('.sync-icon');
        if (syncIcon) syncIcon.classList.add('loading');

        fetch('/api/metrics')
            .then(res => {
                if (!res.ok) throw new Error('API server returned an error status.');
                return res.json();
            })
            .then(data => {
                // Remove error banner
                elErrorBanner.classList.add('hidden');
                
                // Update header states
                const now = new Date();
                elLastUpdateTime.textContent = `最近更新: ${now.toLocaleTimeString()}`;
                
                // Mode Badges
                if (data.github.status === 'online' || data.github.status === 'ok') {
                    elBadgeGithub.className = 'badge badge-live';
                    elBadgeGithub.querySelector('.badge-text').textContent = 'GitHub: 正常';
                } else if (data.github.status === 'cached') {
                    elBadgeGithub.className = 'badge badge-live';
                    elBadgeGithub.querySelector('.badge-text').textContent = 'GitHub: 正常';
                } else {
                    elBadgeGithub.className = 'badge badge-offline';
                    elBadgeGithub.querySelector('.badge-text').textContent = 'GitHub: 连接异常';
                }

                if (data.baidu.status === 'online') {
                    elBadgeBaidu.className = 'badge badge-live';
                    elBadgeBaidu.querySelector('.badge-text').textContent = 'PostHog 统计: 正常';
                } else if (data.baidu.status === 'unconfigured') {
                    elBadgeBaidu.className = 'badge badge-offline';
                    elBadgeBaidu.querySelector('.badge-text').textContent = 'PostHog 统计: 未配置';
                } else {
                    elBadgeBaidu.className = 'badge badge-mock';
                    elBadgeBaidu.querySelector('.badge-text').textContent = 'PostHog 统计: 连接异常';
                }

                // Warmup states
                if (data.warmup && data.warmup.is_warmup) {
                    elWarmupBanner.classList.remove('hidden');
                    const minRemaining = 30 - data.warmup.minutes_tracked;
                    elWarmupBanner.querySelector('.banner-text').textContent = 
                        `系统正在进行数据初始化累积，30分钟增量将在暖机完成后开始精准统计（约需等待 ${minRemaining} 分钟）。`;
                } else {
                    elWarmupBanner.classList.add('hidden');
                }

                // GitHub Card Updates
                elStarsTotal.textContent = data.github.stars_total.toLocaleString();
                updateDeltaBadge(elStarsDeltaContainer, elStarsDelta, data.github.stars_increase_30m);
                setStatus(elStatusGithubStars, data.github.status);

                elDownloadsTotal.textContent = data.github.downloads_total.toLocaleString();
                updateDeltaBadge(elDownloadsDeltaContainer, elDownloadsDelta, data.github.downloads_increase_30m);
                setStatus(elStatusGithubDownloads, data.github.status);
                if (elMsiVersionTag && data.github && data.github.msi_version) {
                    elMsiVersionTag.textContent = data.github.msi_version;
                }

                // Baidu Card Updates
                elUvTotal.textContent = data.baidu.today_total_uv.toLocaleString();
                if (elUvNew && elUvOld) {
                    elUvNew.textContent = data.baidu.today_new_uv.toLocaleString();
                    elUvOld.textContent = data.baidu.today_old_uv.toLocaleString();
                }
                elUvYesterday.textContent = data.baidu.yesterday_total_uv.toLocaleString();
                setStatus(elStatusBaiduUv, data.baidu.status);

                // Update geographical list data
                if (data.baidu_district) {
                    geoData = data.baidu_district;
                    newGeoData = data.baidu_district;
                    countryData = data.baidu_district;
                    if (data.baidu_district.visitors_detail) {
                        traceData = data.baidu_district.visitors_detail;
                    } else if (data.baidu_district.today_visitors_detail) {
                        traceData = { today: data.baidu_district.today_visitors_detail, yesterday: [] };
                    }
                    renderGeoList();
                    renderHourlyNewGeoGrid();
                    renderCountryChartAndList();
                    renderTraceTable();
                }

                if (data.churn) {
                    renderChurnAnalysis(data.churn);
                }

                function renderChurnAnalysis(churn) {
                    if (!churn) return;
                    const elChurnTotal = document.getElementById('churn-total-count');
                    if (elChurnTotal) elChurnTotal.textContent = (churn.churn_total_count || 0).toLocaleString();

                    const elRepeatTotal = document.getElementById('repeat-visitor-total');
                    if (elRepeatTotal) elRepeatTotal.textContent = (churn.repeat_visitor_count || 0).toLocaleString();

                    const elSingleTotal = document.getElementById('single-visitor-total');
                    if (elSingleTotal) elSingleTotal.textContent = (churn.single_visit_count || 0).toLocaleString();

                    const elStickyCount = document.getElementById('sticky-user-count');
                    if (elStickyCount) elStickyCount.textContent = (churn.sticky_user_count || 0).toLocaleString();

                    const elAvgDays = document.getElementById('avg-cultivation-days');
                    if (elAvgDays) elAvgDays.textContent = churn.avg_cultivation_days ? churn.avg_cultivation_days.toFixed(1) : '--';

                    const elGapLaoke = document.getElementById('gap-laoke');
                    if (elGapLaoke) elGapLaoke.textContent = churn.gap_laoke !== undefined ? churn.gap_laoke.toFixed(1) : '--';

                    const elGapXinke = document.getElementById('gap-xinke');
                    if (elGapXinke) elGapXinke.textContent = churn.gap_xinke !== undefined ? churn.gap_xinke.toFixed(1) : '--';

                    const elGapChongfan = document.getElementById('gap-chongfan');
                    if (elGapChongfan) elGapChongfan.textContent = churn.gap_chongfan !== undefined ? churn.gap_chongfan.toFixed(1) : '--';

                    const elGapChenji = document.getElementById('gap-chenji');
                    if (elGapChenji) elGapChenji.textContent = churn.gap_chenji !== undefined ? churn.gap_chenji.toFixed(1) : '--';

                    const tiers = [
                        { key: '7-13', countId: 'churn-count-7-13', pctId: 'churn-pct-7-13', badgeId: 'churn-badge-7-13', barId: 'churn-bar-7-13' },
                        { key: '14-29', countId: 'churn-count-14-29', pctId: 'churn-pct-14-29', badgeId: 'churn-badge-14-29', barId: 'churn-bar-14-29' },
                        { key: '>=30', countId: 'churn-count-30-plus', pctId: 'churn-pct-30-plus', badgeId: 'churn-badge-30-plus', barId: 'churn-bar-30-plus' }
                    ];

                    const tierCounts = churn.tier_counts || {};
                    const tierPcts = churn.tier_pcts || {};
                    const reactivatedByTier = churn.reactivated_by_tier || {};

                    tiers.forEach(t => {
                        const cnt = tierCounts[t.key] || 0;
                        const pct = tierPcts[t.key] || 0;
                        const reactivatedCnt = reactivatedByTier[t.key] || 0;

                        const elCnt = document.getElementById(t.countId);
                        const elPct = document.getElementById(t.pctId);
                        const elBadge = document.getElementById(t.badgeId);
                        const elBar = document.getElementById(t.barId);

                        if (elCnt) elCnt.textContent = `${cnt.toLocaleString()} 人`;
                        if (elPct) elPct.textContent = `(${pct}%)`;
                        if (elBar) elBar.style.width = `${Math.max(2, pct)}%`;

                        if (elBadge) {
                            if (reactivatedCnt > 0) {
                                elBadge.innerHTML = `<span class="minus-n-float-badge">-${reactivatedCnt}</span>`;
                            } else {
                                elBadge.innerHTML = '';
                            }
                        }
                    });
                }

                // Chart updates
                if (data.baidu) {
                    baiduMetrics = data.baidu;
                    updateChartData();
                }

                // Retention Updates
                if (data.retention) {
                    const ret = data.retention;
                    if (elRetentionTotal) elRetentionTotal.textContent = (ret.total_visitors || 0).toLocaleString();
                    
                    const retentionTiers = [
                        { cntId: 'retention-cnt-1', pctId: 'retention-ratio-1', badgeId: 'retention-badge-1', streakKey: 'streak_1', ratioKey: 'ratio_1', netKey: 'net_1' },
                        { cntId: 'retention-cnt-2', pctId: 'retention-ratio-2', badgeId: 'retention-badge-2', streakKey: 'streak_2', ratioKey: 'ratio_2', netKey: 'net_2' },
                        { cntId: 'retention-cnt-3', pctId: 'retention-ratio-3', badgeId: 'retention-badge-3', streakKey: 'streak_3', ratioKey: 'ratio_3', netKey: 'net_3' },
                        { cntId: 'retention-cnt-5', pctId: 'retention-ratio-5', badgeId: 'retention-badge-5', streakKey: 'streak_5', ratioKey: 'ratio_5', netKey: 'net_5' },
                        { cntId: 'retention-cnt-9', pctId: 'retention-ratio-9', badgeId: 'retention-badge-9', streakKey: 'streak_9', ratioKey: 'ratio_9', netKey: 'net_9' },
                        { cntId: 'retention-cnt-15', pctId: 'retention-ratio-15', badgeId: 'retention-badge-15', streakKey: 'streak_15', ratioKey: 'ratio_15', netKey: 'net_15' },
                        { cntId: 'retention-cnt-30', pctId: 'retention-ratio-30', badgeId: 'retention-badge-30', streakKey: 'streak_30', ratioKey: 'ratio_30', netKey: 'net_30' }
                    ];

                    retentionTiers.forEach(t => {
                        const elCnt = document.getElementById(t.cntId);
                        const elPct = document.getElementById(t.pctId);
                        const elBadge = document.getElementById(t.badgeId);

                        if (elCnt) elCnt.textContent = (ret[t.streakKey] || 0).toLocaleString();
                        if (elPct) elPct.textContent = `${ret[t.ratioKey] || 0}%`;

                        if (elBadge) {
                            const netVal = ret[t.netKey] || 0;
                            if (netVal > 0) {
                                elBadge.innerHTML = `<span class="plus-n-float-badge">+${netVal}</span>`;
                            } else if (netVal < 0) {
                                elBadge.innerHTML = `<span class="minus-n-float-badge-red">${netVal}</span>`;
                            } else {
                                elBadge.innerHTML = '';
                            }
                        }
                    });

                    if (retentionChart) {
                        retentionChart.data.datasets[0].data = [
                            ret.streak_1 || 0,
                            ret.streak_2 || 0,
                            ret.streak_3 || 0,
                            ret.streak_5 || 0,
                            ret.streak_9 || 0,
                            ret.streak_15 || 0,
                            ret.streak_30 || 0
                        ];
                        retentionChart.update();
                    }
                }

                if (data.churn) {
                    renderChurnAnalysis(data.churn);
                }
            })
            .catch(err => {
                console.error("Fetch metrics failed:", err);
                elErrorBanner.classList.remove('hidden');
                elErrorMessage.textContent = `与监控服务器同步失败。详细信息: ${err.message}`;
                
                // Fallback stats visual states
                elStarsTotal.textContent = '--';
                elDownloadsTotal.textContent = '--';
                elUvTotal.textContent = '--';
                if (elUvNew && elUvOld) {
                    elUvNew.textContent = '--';
                    elUvOld.textContent = '--';
                }
                elUvYesterday.textContent = '--';
                setStatus(elStatusGithubStars, 'error');
                setStatus(elStatusGithubDownloads, 'error');
                setStatus(elStatusBaiduUv, 'error');
                
                elBadgeGithub.className = 'badge badge-mock';
                elBadgeGithub.querySelector('.badge-text').textContent = '连接中断';
                elBadgeBaidu.className = 'badge badge-mock';
                elBadgeBaidu.querySelector('.badge-text').textContent = '连接中断';
            })
            .finally(() => {
                isFetching = false;
                if (syncIcon) syncIcon.classList.remove('loading');
            });
    }

    // Set up manual trigger
    elBtnRefresh.addEventListener('click', fetchMetrics);

    // Initial load
    try {
        initChart();
    } catch (e) {
        console.error("Failed to initialize chart:", e);
    }
    fetchMetrics();

    // Auto update interval (every 10 seconds)
    setInterval(fetchMetrics, 10000);
});
