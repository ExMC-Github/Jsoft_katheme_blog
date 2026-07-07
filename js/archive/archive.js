// 归档页面JavaScript
let allDates = [];
let allArticles = [];
let openSelect = null;

function initArchivePage() {
    setupEventListeners();
    setupNavHeader();
    setupCustomSelects();
    disableMonthSelect();
    disableDaySelect();
    loadYears();
}

function setupNavHeader() {
    const navHeader = document.getElementById('nav-header');
    if (navHeader) {
        navHeader.classList.add('visible');
    }
    
    const friendsLink = document.getElementById('nav-friends');
    if (friendsLink) {
        friendsLink.addEventListener('click', function(e) {
            if (window.location.pathname === '/notitle') {
                e.preventDefault();
                const friendlyLinksSection = document.getElementById('friendly-links');
                if (friendlyLinksSection) {
                    friendlyLinksSection.scrollIntoView({ behavior: 'smooth' });
                }
            }
        });
    }
}

async function loadYears() {
    try {
        const response = await fetch('/api/articles/dates');
        const data = await response.json();
        allDates = data.dates || [];
        populateYearSelect();
    } catch (error) {
        console.error('加载年份数据失败:', error);
    }
}

function populateYearSelect() {
    const yearOptions = document.getElementById('year-options');
    const yearValue = document.getElementById('year-value');
    const yearTrigger = document.querySelector('#year-select-container .custom-select-trigger');
    
    if (!yearOptions || !yearValue || !yearTrigger) return;
    
    const years = [...new Set(allDates.map(d => d.year))].sort((a, b) => a - b);
    
    yearOptions.innerHTML = '<li data-value="">请选择年份</li>';
    years.forEach(year => {
        const li = document.createElement('li');
        li.dataset.value = year;
        li.textContent = `${year}年`;
        yearOptions.appendChild(li);
    });
    
    yearValue.value = '';
    yearTrigger.textContent = '请选择年份';
}

function disableMonthSelect() {
    const monthOptions = document.getElementById('month-options');
    const monthValue = document.getElementById('month-value');
    const monthTrigger = document.querySelector('#month-select-container .custom-select-trigger');
    const monthContainer = document.getElementById('month-select-container');
    
    if (!monthOptions || !monthValue || !monthTrigger) return;
    
    monthOptions.innerHTML = '<li data-value="">请先选择年份</li>';
    monthValue.value = '';
    monthTrigger.textContent = '请先选择年份';
    if (monthContainer) monthContainer.classList.add('disabled');
}

function disableDaySelect() {
    const dayOptions = document.getElementById('day-options');
    const dayValue = document.getElementById('day-value');
    const dayTrigger = document.querySelector('#day-select-container .custom-select-trigger');
    const dayContainer = document.getElementById('day-select-container');
    
    if (!dayOptions || !dayValue || !dayTrigger) return;
    
    dayOptions.innerHTML = '<li data-value="">请先选择月份</li>';
    dayValue.value = '';
    dayTrigger.textContent = '请先选择月份';
    if (dayContainer) dayContainer.classList.add('disabled');
}

function populateMonthSelect(selectedYear) {
    const monthOptions = document.getElementById('month-options');
    const monthValue = document.getElementById('month-value');
    const monthTrigger = document.querySelector('#month-select-container .custom-select-trigger');
    const monthContainer = document.getElementById('month-select-container');
    
    if (!monthOptions || !monthValue || !monthTrigger) return;
    
    const months = allDates.filter(d => d.year === parseInt(selectedYear));
    const uniqueMonths = [...new Set(months.map(d => d.month))].sort((a, b) => a - b);
    
    monthOptions.innerHTML = '<li data-value="">请选择月份</li>';
    uniqueMonths.forEach(month => {
        const li = document.createElement('li');
        li.dataset.value = month;
        li.textContent = `${month}月`;
        monthOptions.appendChild(li);
    });
    
    monthValue.value = '';
    monthTrigger.textContent = '请选择月份';
    if (monthContainer) monthContainer.classList.remove('disabled');
}

function populateDaySelect(selectedYear, selectedMonth) {
    const dayOptions = document.getElementById('day-options');
    const dayValue = document.getElementById('day-value');
    const dayTrigger = document.querySelector('#day-select-container .custom-select-trigger');
    const dayContainer = document.getElementById('day-select-container');
    
    if (!dayOptions || !dayValue || !dayTrigger) return;
    
    const days = allDates.filter(d => d.year === parseInt(selectedYear) && d.month === parseInt(selectedMonth));
    const uniqueDays = [...new Set(days.map(d => d.day))].sort((a, b) => a - b);
    
    dayOptions.innerHTML = '<li data-value="">请选择日期</li>';
    uniqueDays.forEach(day => {
        const li = document.createElement('li');
        li.dataset.value = day;
        li.textContent = `${day}日`;
        dayOptions.appendChild(li);
    });
    
    dayValue.value = '';
    dayTrigger.textContent = '请选择日期';
    if (dayContainer) dayContainer.classList.remove('disabled');
}

function setupCustomSelects() {
    const selects = document.querySelectorAll('.custom-select');
    
    selects.forEach(select => {
        const trigger = select.querySelector('.custom-select-trigger');
        
        if (trigger) {
            trigger.addEventListener('click', function(e) {
                e.stopPropagation();
                toggleSelect(select);
            });
        }
    });
    
    document.addEventListener('click', function(e) {
        const target = e.target;
        
        if (target.closest('.custom-select-options li')) {
            e.stopPropagation();
            const li = target.closest('.custom-select-options li');
            const select = li.closest('.custom-select');
            const options = select.querySelector('.custom-select-options');
            const hiddenInput = select.querySelector('input[type="hidden"]');
            const triggerEl = select.querySelector('.custom-select-trigger');
            
            const value = li.dataset.value;
            const text = li.textContent;
            
            if (hiddenInput) hiddenInput.value = value;
            if (triggerEl) triggerEl.textContent = text;
            
            options.querySelectorAll('li').forEach(item => item.classList.remove('selected'));
            li.classList.add('selected');
            
            closeSelect(select);
            handleSelectChange(select);
            return;
        }
        
        if (!e.target.closest('.custom-select')) {
            closeAllSelects();
        }
    });
}

function toggleSelect(select) {
    if (select.classList.contains('disabled')) return;
    
    if (openSelect && openSelect !== select) {
        closeSelect(openSelect);
    }
    
    select.classList.toggle('open');
    openSelect = select.classList.contains('open') ? select : null;
}

function closeSelect(select) {
    select.classList.remove('open');
    if (openSelect === select) {
        openSelect = null;
    }
}

function closeAllSelects() {
    document.querySelectorAll('.custom-select.open').forEach(select => {
        closeSelect(select);
    });
}

function handleSelectChange(select) {
    const id = select.id;
    
    if (id === 'year-select-container') {
        const yearValue = document.getElementById('year-value').value;
        if (yearValue) {
            populateMonthSelect(yearValue);
            disableDaySelect();
        } else {
            disableMonthSelect();
            disableDaySelect();
        }
    } else if (id === 'month-select-container') {
        const yearValue = document.getElementById('year-value').value;
        const monthValue = document.getElementById('month-value').value;
        if (monthValue) {
            populateDaySelect(yearValue, monthValue);
        } else {
            disableDaySelect();
        }
    }
}

function setupEventListeners() {
    const searchBtn = document.getElementById('search-btn');
    
    if (searchBtn) {
        searchBtn.addEventListener('click', performSearch);
    }
}

function performSearch() {
    const yearValue = document.getElementById('year-value');
    const monthValue = document.getElementById('month-value');
    const dayValue = document.getElementById('day-value');
    
    const year = yearValue.value;
    const month = monthValue.value;
    const day = dayValue.value;
    
    if (!year && (month || day)) {
        showSmallDialog('请先选择年份', 'warning');
        return;
    }
    
    if (year && !month && day) {
        showSmallDialog('请先选择月份', 'warning');
        return;
    }
    
    searchArticles(year, month, day);
}

async function searchArticles(year, month, day) {
    const archiveList = document.getElementById('archiveList');
    if (!archiveList) return;
    
    archiveList.innerHTML = '<p class="no-articles">加载中...</p>';
    
    try {
        let url = '/api/articles/filter?';
        const params = [];
        
        if (year) params.push(`year=${year}`);
        if (month) params.push(`month=${month}`);
        if (day) params.push(`day=${day}`);
        
        url += params.join('&');
        
        const response = await fetch(url);
        const data = await response.json();
        allArticles = data.articles || [];
        
        renderArticles(allArticles);
        
        showSmallDialog(`已查询到${allArticles.length}条结果`, 'success');
    } catch (error) {
        console.error('搜索文章失败:', error);
        archiveList.innerHTML = '<p class="no-articles">搜索失败，请重试</p>';
        showSmallDialog('搜索失败，请重试', 'error');
    }
}

function renderArticles(articles) {
    const archiveList = document.getElementById('archiveList');
    if (!archiveList) return;
    
    if (articles.length === 0) {
        archiveList.innerHTML = '<p class="no-articles">没有找到符合条件的文章</p>';
        return;
    }
    
    archiveList.innerHTML = '';
    
    articles.forEach(article => {
        const articleElement = document.createElement('div');
        articleElement.className = 'blog-item';
        articleElement.onclick = () => {
            window.location.href = `/read/${article.category}/${article.id}`;
        };
        
        const iconHtml = article.has_icon 
            ? `<img src="/read/${article.category}/${article.id}/icon" alt="${article.title}">` 
            : '<div class="default-icon">📄</div>';
        
        articleElement.innerHTML = `
            <div class="blog-item-content">
                <div class="blog-icon">
                    ${iconHtml}
                </div>
                <div class="blog-info">
                    <h3 class="blog-title">${escapeHtml(article.title)}</h3>
                    <p class="blog-small-title">${escapeHtml(article.small_title || '无简介')}</p>
                    ${article.pub_date ? `<p class="blog-date">${article.pub_date}</p>` : ''}
                </div>
            </div>
        `;
        
        archiveList.appendChild(articleElement);
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', () => {
    initArchivePage();
});