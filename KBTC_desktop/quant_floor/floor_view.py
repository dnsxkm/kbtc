"""Scalable pixel office for the three futures strategies."""
import tkinter as tk
from decimal import Decimal as D


BG = "#0b0c0f"
PANEL = "#16181d"
INK = "#ede8df"
MUTED = "#9ea2aa"
MINT = "#88e6c4"
GOLD = "#ffc56b"
UP = "#3ecf7a"
DOWN = "#ff5f7e"
CARD = "#111317"
CHIP = "#2a2d34"


class Floor(tk.Canvas):
    def __init__(self, parent, levels, selection):
        super().__init__(parent, bg="#0f1115", highlightthickness=0, height=140, width=400)
        self.levels = levels
        self.selection = selection
        self.signals = ["대기"] * len(levels)
        self.bubble = None  # (kind, title, lines)
        self.visible, self.typing, self.reveal, self.tick = True, False, 0, 0
        self.geo = (0, 0, 1)
        self.bind("<Button-1>", lambda e: self.show())
        self.data = {}
        self.ticker_x, self.ticker_w = 0.0, 300
        self.cheek_y = 219
        self.after(500, self._scroll)
        self.bind("<Configure>", lambda e: self.paint())
        selection.trace_add("write", lambda *_: self.paint())

    def paint(self):
        """트레이딩 본부: 벽면 대형 스크린 3대 + 책상 모니터 2대 + LED 시세 띠 + 운영자."""
        self.delete("all")
        w,h = self.winfo_width(), self.winfo_height()
        scale=min(w/600,h/300)
        if scale<=0.05:
            return
        ox,oy=(w-600*scale)/2,(h-300*scale)/2
        self.geo=(ox,oy,scale)
        X=lambda v: ox+v*scale
        Y=lambda v: oy+v*scale
        def box(x,y,a,b,color):
            self.create_rectangle(X(x),Y(y),X(a),Y(b),fill=color,outline="")
        def txt(x,y,s,color,size,anchor="w",bold=True):
            self.create_text(X(x),Y(y),text=s,fill=color,anchor=anchor,
                             font=("Malgun Gothic",max(7,int(size*scale)),"bold" if bold else "normal"))
        def spark(x0,y0,x1,y1,vals,color,width=1.4):
            vals=[float(v) for v in vals if v is not None]
            if len(vals)<2:
                return
            lo,hi=min(vals),max(vals); rng=(hi-lo) or 1
            pts=[]
            for i,v in enumerate(vals):
                pts+= [X(x0+(x1-x0)*i/(len(vals)-1)), Y(y1-(y1-y0)*(v-lo)/rng)]
            self.create_line(*pts,fill=color,width=max(1,width*scale))
        def screen(x0,y0,x1,y1):
            box(x0-4,y0-4,x1+4,y1+4,"#1c1d22")
            box(x0-2,y0-2,x1+2,y1+2,"#2a2c33")
            box(x0,y0,x1,y1,"#0c1311")
        dd=self.data
        tone=lambda c: UP if c is not None and c>0 else DOWN if c is not None and c<0 else INK
        pct=lambda c: "—" if c is None else f"{c:+.2f}%"
        num=lambda v,f=",.1f": "—" if v is None else format(v,f)

        # 창밖 노을 스카이라인
        box(12,10,588,106,"#484663")
        for i,color in enumerate(("#35324e","#49405f","#62516e","#87657a","#a77782")):
            box(18,16+i*17,582,34+i*17,color)
        box(454,25,470,41,"#ffdc9f")
        box(451,28,473,38,"#ffdc9f")
        for i in range(34):
            x=18+i*17
            top=52+(i*17+i*i)%34
            box(x,top,x+16,101,"#302f48")
            for y in range(top+5,97,9):
                box(x+4,y,x+7,y+2,"#a88678")
        for x in range(16,585,94):
            box(x,15,x+5,104,"#28293d")
        box(12,102,588,109,"#a58d87")
        # 벽
        box(12,109,588,284,"#2e2f3a")
        for y in range(124,282,16):
            box(12,y,588,y+1,"#383946")
            for x in range(34+(y%32)*2,585,70):
                box(x,y,x+1,y+16,"#363744")
        # 천장에 매단 브리핑 모니터
        for cx_ in (210,390):
            box(cx_,10,cx_+2,26,"#1c1d22")
        screen(160,26,440,100)
        self.brief_box=(160,26,440,100)
        # LED 시세 띠 (애니메이션은 draw_ticker)
        box(12,109,588,121,"#060607")
        self.ticker_box=(12,109,588,121)

        # ── 벽면 대형 스크린 ──
        # NASDAQ
        screen(28,132,188,180)
        n=dd.get("ndx") or {}
        txt(33,138,"NASDAQ",MUTED,6.5)
        txt(183,138,"LIVE" if n.get("live") else "CLOSED",UP if n.get("live") else MUTED,5.5,"e")
        txt(33,151,num(n.get("price"),",.0f"),INK,10)
        txt(183,151,pct(n.get("chg")),tone(n.get("chg")),7,"e")
        spark(33,159,183,177,n.get("closes") or [],tone(n.get("chg")))
        # BTCUSDT 메인 (일봉 + 50일선 = 전략 차트)
        screen(200,128,400,184)
        sig=dd.get("signal")
        txt(205,134,"BTCUSDT PERP · 1D",MUTED,6.5)
        if sig:
            box(366,129.5,399,139,UP if sig>0 else DOWN)
            txt(382.5,134.5,"LONG" if sig>0 else "SHORT","#0b0c0f",5.5,"center")
        txt(205,147,num(dd.get("btc")),INK,11)
        txt(395,147,pct(dd.get("btc_chg")),tone(dd.get("btc_chg")),7,"e")
        cl=dd.get("btc_daily") or []
        if len(cl)>=60:
            view=cl[-45:]
            ma=[sum(cl[i-49:i+1])/50 for i in range(len(cl)-45,len(cl))]
            vals=[float(v) for v in view+ma]
            lo,hi=min(vals),max(vals); rng=(hi-lo) or 1
            def line(series,color,wd):
                pts=[]
                for i,v in enumerate(series):
                    pts+=[X(205+190*i/44),Y(181-(181-155)*(float(v)-lo)/rng)]
                self.create_line(*pts,fill=color,width=max(1,wd*scale))
            line(ma,GOLD,1.2)
            line(view,INK,1.4)
            txt(362,134,f"50MA {float(ma[-1]):,.0f}",GOLD,5.5,"e")
        # ETHUSDT
        screen(412,132,572,180)
        txt(417,138,"ETHUSDT PERP",MUTED,6.5)
        txt(417,151,num(dd.get("eth"),",.2f"),INK,10)
        txt(567,151,pct(dd.get("eth_chg")),tone(dd.get("eth_chg")),7,"e")
        spark(417,159,567,177,dd.get("eth_1h") or [],tone(dd.get("eth_chg")))

        # ── 책상 ──
        box(100,226,500,233,"#8f6b5c")
        box(100,233,500,238,"#6b4e4a")
        for leg in (108,486):
            box(leg,238,leg+6,262,"#1d1e25")
        # 책상 모니터: SIGNAL / FUNDING
        for x0 in (140,372):
            box(x0+38,218,x0+50,226,"#24252c")
            box(x0+30,224,x0+58,226,"#3a3b44")
        screen(140,186,228,220)
        txt(144,191,"SIGNAL · 50MA",MUTED,5)
        if sig:
            txt(144,202,"LONG" if sig>0 else "SHORT",UP if sig>0 else DOWN,8.5)
        txt(224,202,f"{dd['gap']:+.1f}%" if dd.get("gap") is not None else "—",INK,6,"e")
        txt(144,214,f"다음 판단 {dd.get('next','—')}",MUTED,4.8,bold=False)
        screen(372,186,460,220)
        txt(376,191,"FUNDING · 8H",MUTED,5)
        fr=dd.get("funding")
        txt(376,202,"—" if fr is None else f"{fr*100:+.4f}%",INK,7.5)
        txt(456,214,f"Mark {num(dd.get('mark'))}",MUTED,4.8,"e",bold=False)
        # 키보드·머그·화분
        box(236,222,284,226,"#3b3d47")
        for k in range(10):
            box(238+k*4.6,223,241+k*4.6,225,"#5a5c66")
        box(470,214,480,226,"#edd4b5"); box(480,217,483,222,"#edd4b5")
        box(528,246,548,262,"#7a4a3a"); box(524,232,552,248,"#4f8a5b"); box(532,222,544,236,"#5fa36b")

        # ── 운영자 ──
        x=300
        color=MINT
        box(x-12,198,x+8,206,"#423043")
        box(x-16,202,x+11,212,"#423043")
        box(x-13,206,x+13,224,"#e8b58f")
        box(x-16,202,x+11,209,"#423043")
        box(x-7,214,x-4,217,"#2a2230"); box(x+3,214,x+6,217,"#2a2230")
        box(x-19,222,x+19,244,color)
        box(x-14,232,x+14,248,"#515b76" if False else "#4f5563")
        box(x-3,248,x+3,255,"#25262e")
        box(x-13,255,x+13,258,"#25262e")
        # 하단 명판: 전략 신호
        box(226,264,374,292,MINT)
        box(228,266,372,290,"#15171c")
        txt(300,278,f"추세 분석  ·  {self.signals[0]}",MINT,10,"center")
        self.cheek_y=219
        self.draw_ticker()
        self.draw_bubble()

    def draw_ticker(self):
        """LED 시세 띠: 오른쪽에서 왼쪽으로 흐른다."""
        self.delete("ticker")
        if not hasattr(self,"ticker_box"):
            return
        ox,oy,scale=self.geo
        x0,y0,x1,y1=self.ticker_box
        items=self.data.get("tape") or ["KBTC  HQ  ONLINE"]
        s="      ".join(items)
        tid=self.create_text(ox+(x1+self.ticker_x)*scale,oy+(y0+y1)/2*scale,text=s,anchor="w",fill="#ffb347",
                             font=("Menlo",max(7,int(6.5*scale)),"bold"),tags=("ticker",))
        bb=self.bbox(tid)
        self.ticker_w=(bb[2]-bb[0])/scale if bb else 300
        W=self.winfo_width()
        self.create_rectangle(0,oy+y0*scale,ox+x0*scale,oy+y1*scale,fill=self["bg"],outline="",tags=("ticker",))
        self.create_rectangle(ox+x1*scale,oy+y0*scale,W,oy+y1*scale,fill=self["bg"],outline="",tags=("ticker",))
        self.tag_raise("bubble")

    def _scroll(self):
        if hasattr(self,"ticker_box"):
            x0,y0,x1,y1=self.ticker_box
            self.ticker_x-=0.8
            if self.ticker_x < -(x1-x0)-self.ticker_w:
                self.ticker_x=0
            ox,oy,scale=self.geo
            items=self.find_withtag("ticker")
            if items:
                self.coords(items[0],ox+(x1+self.ticker_x)*scale,oy+(y0+y1)/2*scale)
        self.after(50,self._scroll)

    # ---------- 브리핑 모니터 (BTC 스크린 위, 항상 표시 + 타자 효과) ----------
    def show(self, ms=None):
        """새 브리핑을 한 글자씩 타이핑한다. 본부 그림을 클릭하면 다시 재생."""
        self.reveal = 0
        if not self.typing:
            self.typing = True
            self._animate()

    def hide(self):
        pass

    def _animate(self):
        if not self.bubble:
            self.typing = False
            return
        total = len(self.bubble[1]) + len("\n".join(self.bubble[2]))
        self.reveal += 2
        self.tick += 1
        self.draw_bubble()
        if self.reveal < total:
            self.after(35, self._animate)
        else:
            self.typing = False
            self.draw_bubble()

    def draw_bubble(self):
        self.delete("bubble")
        if not (self.bubble and hasattr(self, "brief_box")):
            return
        ox, oy, scale = self.geo
        kind, title, lines, style = self.bubble
        teto = style == "teto"
        x0, y0, x1, y1 = self.brief_box
        X = lambda v: ox + v * scale
        Y = lambda v: oy + v * scale
        tag = ("bubble",)
        head = {"long": UP, "short": DOWN}.get(kind, "#ffffff" if teto else "#ffc98b")
        body = "#ffffff" if teto else "#f3e6d8"
        n = int(self.reveal) if self.typing else 10 ** 6
        t_show = title[:n]
        b_show = "\n".join(lines)[:max(0, n - len(title))]
        cursor = "▌" if self.typing and self.tick % 2 == 0 else ""
        self.create_text(X(x0 + 6), Y(y0 + 5), text="BRIEFING", anchor="w", fill=MUTED,
                         font=("Malgun Gothic", max(7, int(5 * scale)), "bold"), tags=tag)
        self.create_text(X(x1 - 6), Y(y0 + 5), text=("테토" if teto else "에겐") + " MODE", anchor="e",
                         fill="#ffffff" if teto else "#ffb3c1", font=("Malgun Gothic", max(7, int(5 * scale)), "bold"), tags=tag)
        self.create_text(X(x0 + 6), Y(y0 + 15), text=t_show + (cursor if len(t_show) < len(title) else ""), anchor="w",
                         fill=head, font=("Malgun Gothic", max(8, int(8 * scale)), "bold"), tags=tag)
        self.create_text(X(x0 + 6), Y(y0 + 22), text=b_show + (cursor if len(t_show) >= len(title) else ""), anchor="nw",
                         fill=body, width=(x1 - x0 - 12) * scale, justify="left",
                         font=("Malgun Gothic", max(7, int(6.2 * scale)), "bold" if teto else "normal"), tags=tag)
        if self.typing and not teto:  # 말하는 동안 볼터치
            for chx in (300 - 11, 300 + 7):
                self.create_rectangle(X(chx), Y(self.cheek_y), X(chx + 4), Y(self.cheek_y + 3), fill="#ff9fb0", outline="", tags=tag)

class Pill(tk.Canvas):
    """OKX 같은 둥근 버튼 (macOS에서도 색이 그대로 나온다)."""
    def __init__(self,parent,text,cmd,fill,hover,fg="#ffffff",height=36):
        super().__init__(parent,bg=PANEL,height=height,width=1,highlightthickness=0,cursor="hand2")
        self.text,self.cmd,self.fill,self.hover,self.fg=text,cmd,fill,hover,fg
        self.cur=fill
        self.bind("<Configure>",lambda e: self.draw())
        self.bind("<Enter>",lambda e: self.paint_as(self.hover))
        self.bind("<Leave>",lambda e: self.paint_as(self.fill))
        self.bind("<ButtonRelease-1>",lambda e: self.cmd())

    def paint_as(self,color):
        self.cur=color
        self.draw()

    def draw(self):
        self.delete("all")
        w,h=self.winfo_width(),self.winfo_height()
        r=h/2
        self.create_oval(0,0,h,h,fill=self.cur,outline="")
        self.create_oval(w-h,0,w,h,fill=self.cur,outline="")
        self.create_rectangle(r,0,w-r,h,fill=self.cur,outline="")
        self.create_text(w/2,h/2,text=self.text,fill=self.fg,font=("Malgun Gothic",11,"bold"))


FLAG_RED, FLAG_BLUE, TAEGUK_BLUE = "#cd2e3a", "#2f6bd0", "#0047a0"


def draw_taeguk(c,cx,cy,r):
    """태극 문양만 (위 빨강, 아래 파랑, 태극기와 같은 기울기)."""
    import math
    a=math.atan2(2,3)
    ca,sa=math.cos(a),math.sin(a)
    rot=lambda px,py:(cx+(px-cx)*ca-(py-cy)*sa, cy+(px-cx)*sa+(py-cy)*ca)
    pts=[]
    for i in range(61):
        th=math.pi*i/60; pts.append(rot(cx+r*math.cos(th),cy-r*math.sin(th)))
    for i in range(41):
        th=math.pi+math.pi*i/40; pts.append(rot(cx-r/2+r/2*math.cos(th),cy-r/2*math.sin(th)))
    for i in range(41):
        th=math.pi-math.pi*i/40; pts.append(rot(cx+r/2+r/2*math.cos(th),cy-r/2*math.sin(th)))
    c.create_oval(cx-r,cy-r,cx+r,cy+r,fill=TAEGUK_BLUE,outline="")
    c.create_polygon([v for p in pts for v in p],fill=FLAG_RED,outline="")



def draw_logo(c):
    import tkinter.font as tkfont
    draw_taeguk(c,19,19,16)
    f=tkfont.Font(family="Malgun Gothic",size=21,weight="bold")
    x=46
    for ch,col in zip("KOREA",(FLAG_RED,FLAG_BLUE,FLAG_RED,FLAG_BLUE,FLAG_RED)):
        c.create_text(x,19,text=ch,anchor="w",fill=col,font=f)
        x+=f.measure(ch)
    x+=f.measure(" ")
    c.create_text(x,19,text="BITCOIN",anchor="w",fill="#ffffff",font=f)
    c.configure(width=x+f.measure("BITCOIN")+6)


class WeightSlider(tk.Canvas):
    """진입 비중 드래그 바 (0/25/50/75/100% 눈금, 입력칸과 양방향 연동)."""
    def __init__(self,parent,d):
        super().__init__(parent,bg=PANEL,height=36,highlightthickness=0,cursor="hand2")
        self.d=d
        self.value=30
        self.bind("<Configure>",lambda e: self.draw())
        self.bind("<Button-1>",self.drag)
        self.bind("<B1-Motion>",self.drag)
        d.amount.bind("<KeyRelease>",self.from_entry)

    def span(self):
        return 12,max(self.winfo_width()-14,40)

    def drag(self,e):
        if self.d.running:
            return
        x0,x1=self.span()
        v=round(max(0,min(100,(e.x-x0)/(x1-x0)*100)))
        for tick in (0,25,50,75,100):
            if abs(v-tick)<=2:
                v=tick
        v=max(v,1)
        self.value=v
        self.d.amount.delete(0,"end")
        self.d.amount.insert(0,str(v))
        self.draw()

    def from_entry(self,e=None):
        try:
            self.value=max(0,min(100,float(self.d.amount.get().strip().rstrip("%"))))
        except ValueError:
            return
        self.draw()

    def draw(self):
        self.delete("all")
        x0,x1=self.span()
        y=11
        xv=x0+(x1-x0)*self.value/100
        self.create_line(x0,y,x1,y,fill="#33363d",width=4,capstyle="round")
        self.create_line(x0,y,xv,y,fill=MINT,width=4,capstyle="round")
        for tick in (0,25,50,75,100):
            x=x0+(x1-x0)*tick/100
            self.create_oval(x-5,y-5,x+5,y+5,fill=MINT if tick<=self.value else "#33363d",outline=PANEL,width=2)
            self.create_text(x,y+19,text=f"{tick}%",fill=MUTED,font=("Malgun Gothic",9))
        self.create_oval(xv-8,y-8,xv+8,y+8,fill=INK,outline=MINT,width=3)


def build(d, levels):
    root=d.root
    root.configure(bg=BG)
    root.geometry("1340x880")
    root.minsize(1000,600)
    def label(parent,text,size=10,color=INK,bg=PANEL):
        return tk.Label(parent,text=text,bg=bg,fg=color,font=("Malgun Gothic",size,"bold"),anchor="w")
    header=tk.Frame(root,bg=BG)
    header.pack(fill="x",padx=20,pady=(14,10))
    import os
    try:  # 앱 아이콘 (Dock/작업표시줄)
        d.app_icon=tk.PhotoImage(file=os.path.join(os.path.dirname(__file__),"assets","icon.png"))
        root.iconphoto(True,d.app_icon)
    except Exception:
        pass
    png=os.path.join(os.path.dirname(__file__),"assets","logo.png")
    try:
        d.logo_img=tk.PhotoImage(file=png)
        tk.Label(header,image=d.logo_img,bg=BG,bd=0).pack(side="left")
    except Exception:
        logo=tk.Canvas(header,bg=BG,highlightthickness=0,height=38,width=330)
        logo.pack(side="left")
        draw_logo(logo)
    d.chg_lbl=label(header,"",11,MUTED,BG)
    d.chg_lbl.pack(side="right")
    d.price_lbl=label(header,"—",19,INK,BG)
    d.price_lbl.pack(side="right",padx=(0,10))
    label(header,"BTC   현재가",11,MUTED,BG).pack(side="right",padx=(0,10))
    cards=tk.Frame(root,bg=BG)
    cards.pack(fill="x",padx=20,pady=(0,10))
    d.tiles=[]
    for i,title in enumerate(("포지션  /  BTC","매수 · 매도  /  24H","실현 손익  /  USDT","청산 원금 수익률  /  비용 전")):
        cards.columnconfigure(i,weight=1,uniform="metric")
        card=tk.Frame(cards,bg=PANEL,padx=12,pady=8)
        card.grid(row=0,column=i,sticky="ew",padx=(0,5 if i<3 else 0))
        label(card,title,9,MUTED).pack(fill="x")
        val=label(card,"—",17)
        val.pack(fill="x")
        d.tiles.append(val)
    main=tk.Frame(root,bg=BG)
    main.pack(fill="both",expand=True,padx=20,pady=(0,12))
    # 맨 오른쪽: 접었다 펴는 API 탭 + API (기본 세팅) 칸
    rail=tk.Label(main,bg="#1e2026",fg=GOLD,cursor="hand2",width=3,font=("Malgun Gothic",11,"bold"),justify="center")
    rail.pack(side="right",fill="y",padx=(8,0))
    api=tk.Frame(main,bg=PANEL,padx=14,pady=8,width=250)
    api.pack(side="right",fill="y",padx=(10,0))
    api.pack_propagate(False)
    def toggle_api(show=None):
        show=not api.winfo_ismapped() if show is None else show
        if show and not api.winfo_ismapped():
            api.pack(side="right",fill="y",padx=(10,0),before=rail)
        elif not show and api.winfo_ismapped():
            api.pack_forget()
        rail.configure(text=("▶" if show else "◀")+"\n\nA\nP\nI\n\n"+("접기" if show else "열기").replace("","\n").strip())
    d.toggle_api=toggle_api
    rail.bind("<Button-1>",lambda e: toggle_api())
    rail.bind("<Enter>",lambda e: rail.configure(bg="#2a2c31"))
    rail.bind("<Leave>",lambda e: rail.configure(bg="#1e2026"))
    # 오른쪽 콘솔은 창이 낮아지면 스크롤(트랙패드/휠)로 본다.
    side_wrap=tk.Frame(main,bg=PANEL)
    side_wrap.pack(side="right",fill="y",padx=(10,0))
    sc=tk.Canvas(side_wrap,bg=PANEL,highlightthickness=0,width=300)
    sc.pack(side="left",fill="y")
    side=tk.Frame(sc,bg=PANEL,padx=14,pady=8)
    sc.create_window(0,0,window=side,anchor="nw")
    side.bind("<Configure>",lambda e: sc.configure(scrollregion=sc.bbox("all"),width=side.winfo_reqwidth()))
    def wheel(e):
        if not str(e.widget).startswith(str(side_wrap)) or sc.yview()==(0.0,1.0):
            return
        step=-int(e.delta/120) if abs(e.delta)>=120 else -e.delta
        sc.yview_scroll(step,"units")
    root.bind_all("<MouseWheel>",wheel)
    left=tk.Frame(main,bg=PANEL)
    left.pack(fill="both",expand=True)
    label(left,"트레이딩 본부",14).pack(anchor="w",padx=14,pady=8)
    d.floor=Floor(left,levels,d.level)
    d.floor.pack(fill="both",expand=True)
    state_lbl=tk.Label(left,textvariable=d.state,bg="#1e2127",fg=MINT,anchor="w",padx=12,pady=7)
    # 포지션 카드 (거래소 앱 포지션 화면 형식)
    card=tk.Frame(left,bg=CARD,padx=14,pady=10)
    top=tk.Frame(card,bg=CARD)
    top.pack(fill="x")
    label(top,"BTC",13,INK,CARD).pack(side="left")
    def chip(text):
        c=tk.Label(top,text=text,bg=CHIP,fg=INK,padx=7,pady=1,font=("Malgun Gothic",10,"bold"))
        c.pack(side="left",padx=(8,0))
        return c
    d.pos_side,d.pos_mode,d.pos_lev=chip("포지션 없음"),chip("—"),chip("—x")
    d.pos_pnl=label(top,"",14,INK,CARD)
    d.pos_pnl.pack(side="right")
    label(top,"미실현 손익 (USDT)  ",9,MUTED,CARD).pack(side="right")
    grid=tk.Frame(card,bg=CARD)
    grid.pack(fill="x",pady=(8,0))
    d.pos_vals={}
    for i,(k,title) in enumerate([("size","포지션 규모 (USDT)"),("margin","증거금 (USDT)"),("ratio","마진 비율"),
                                  ("entry","진입가"),("mark","시장가 (Mark)"),("liq","청산가")]):
        grid.columnconfigure(i%3,weight=1,uniform="pos")
        cell=tk.Frame(grid,bg=CARD)
        cell.grid(row=i//3,column=i%3,sticky="ew",pady=(0,6))
        label(cell,title,9,MUTED,CARD).pack(fill="x")
        d.pos_vals[k]=label(cell,"—",14,INK,CARD)
        d.pos_vals[k].pack(fill="x")
    log_lbl=label(left,"체결 · 활동 기록",11)
    d.log=tk.Text(left,height=4,width=32,state="disabled",bg="#0e0f12",fg=INK,relief="flat",padx=12,pady=6)
    # 아래 요소를 먼저 바닥에 고정하고, 창이 낮아지면 그림(트레이딩 본부)이 줄어든다.
    d.floor.pack_forget()
    d.log.pack(side="bottom",fill="x",padx=8,pady=(0,8))
    log_lbl.pack(side="bottom",anchor="w",padx=14,pady=6)
    card.pack(side="bottom",fill="x",padx=8,pady=(8,0))
    state_lbl.pack(side="bottom",fill="x")
    d.floor.pack(fill="both",expand=True)
    from tkinter import ttk
    style=ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCombobox",fieldbackground="#24272e",foreground=INK,background="#33363d")
    style.map("TCombobox",fieldbackground=[("readonly","#24272e")],foreground=[("readonly",INK)])
    def field(title,var=None,options=None,secret=False,parent=None):
        parent=parent or side
        label(parent,title,9,MUTED,parent["bg"]).pack(fill="x",pady=(4,1))
        widget=(ttk.Combobox(parent,textvariable=var,values=options,state="readonly",width=22) if options else
                tk.Entry(parent,show="*" if secret else "",bg="#24272e",fg=INK,insertbackground=INK,relief="flat",font=("Consolas",11)))
        widget.pack(fill="x",ipady=2)
        return widget
    # ── API 칸 ──
    head=tk.Frame(api,bg=PANEL)
    head.pack(fill="x")
    label(head,"API",14).pack(side="left")
    x=tk.Label(head,text=" ✕ ",bg=PANEL,fg=MUTED,cursor="hand2",font=("Malgun Gothic",12,"bold"))
    x.pack(side="right")
    x.bind("<Button-1>",lambda e: toggle_api(False))
    q=tk.Label(head,text=" ? ",bg="#2a2c31",fg=GOLD,cursor="hand2",font=("Malgun Gothic",12,"bold"))
    q.pack(side="right",padx=(0,6))
    q.bind("<Button-1>",lambda e: api_help(root))
    label(api,"바이낸스 선물 계좌 연결 (기본 세팅)",9,MUTED).pack(fill="x",pady=(2,4))
    d.select=field("계좌 환경",d.mode,["Demo","Live"],parent=api)
    d.key=field("API Key",secret=True,parent=api)
    d.secret=field("Secret Key",secret=True,parent=api)
    Pill(api,"계좌 연결 · 조회",d.connect,"#2a2c31","#3a3d44").pack(fill="x",pady=(12,0))
    how=tk.Label(api,text="? API 키 만드는 법",bg=PANEL,fg=GOLD,cursor="hand2",font=("Malgun Gothic",10,"bold"))
    how.pack(anchor="w",pady=(10,0))
    how.bind("<Button-1>",lambda e: api_help(root))
    tk.Label(api,text="키는 이 PC 파일에 저장되지 않아요.\n앱을 다시 켜면 다시 넣어 주세요.",bg=PANEL,fg=MUTED,
             justify="left",anchor="w",font=("Malgun Gothic",9)).pack(fill="x",pady=(6,0))
    toggle_api(True)
    # ── TRADE 칸 ──
    label(side,"TRADE",14).pack(fill="x")
    d.strategy=field("실행 전략",d.level,levels)
    d.persona_box=field("트레이더 말투",d.persona,["에겐","테토"])
    d.amount=field("진입 비중 (%)")
    d.amount.insert(0,"30")
    d.weight_slider=WeightSlider(side,d)
    d.weight_slider.pack(fill="x",pady=(4,0))
    d.lev_entry=field("배율 (x)  ·  Enter로 즉시 적용")
    d.lev_entry.insert(0,"10")
    d.lev_entry.bind("<Return>",d.apply_leverage)
    bt=tk.Label(side,text="배율별 백테스트 보기 (BTC · 비중 30%) ›",bg=PANEL,fg=GOLD,cursor="hand2",
                font=("Malgun Gothic",10,"bold"),anchor="w")
    bt.pack(fill="x",pady=(6,0))
    bt.bind("<Button-1>",lambda e: backtest_window(root,d))
    # OKX 스타일 둥근(pill) 버튼
    row=tk.Frame(side,bg=PANEL)
    row.pack(fill="x",pady=(12,0))
    row.columnconfigure(0,weight=3)
    row.columnconfigure(1,weight=2)
    Pill(row,"퀀트 트레이딩 시작",d.start,"#25a750","#30bd5f").grid(row=0,column=0,sticky="ew",padx=(0,4))
    Pill(row,"중지",d.stop,"#d6455d","#e65c73").grid(row=0,column=1,sticky="ew",padx=(4,0))
    # 전체 계좌
    label(side,"Asset",13).pack(fill="x",pady=(10,2))
    d.acct={}
    for k,title in [("equity","총 자산"),("wallet","지갑 잔고"),("upnl","미실현 손익"),
                    ("avail","사용 가능"),("used","사용 증거금"),("lev","배율 · 모드")]:
        row=tk.Frame(side,bg=PANEL)
        row.pack(fill="x",pady=1)
        label(row,title,10,MUTED).pack(side="left")
        d.acct[k]=label(row,"—",11)
        d.acct[k].pack(side="right")


def show_account(d,pos,acct):
    """v2/positionRisk 한 줄과 v3/account 응답으로 화면을 채운다."""
    amt=D(pos["positionAmt"]); lev=D(pos["leverage"])
    mode="Cross" if pos["marginType"].lower().startswith("cross") else "Isolated"
    equity=D(acct["totalMarginBalance"]); upnl_all=D(acct["totalUnrealizedProfit"])
    maint=D(acct["totalMaintMargin"])
    tone=lambda x: UP if x>0 else DOWN if x<0 else INK
    d.acct["equity"].configure(text=f"{equity:,.2f} USDT")
    d.acct["wallet"].configure(text=f"{D(acct['totalWalletBalance']):,.2f} USDT")
    d.acct["upnl"].configure(text=f"{upnl_all:+,.2f} USDT",fg=tone(upnl_all))
    d.acct["avail"].configure(text=f"{D(acct['availableBalance']):,.2f} USDT")
    d.acct["used"].configure(text=f"{D(acct['totalInitialMargin']):,.2f} USDT")
    d.acct["lev"].configure(text=f"{lev}x · {mode}",fg=GOLD)
    d.pos_lev.configure(text=f"{lev}x")
    d.pos_mode.configure(text=mode)
    d.tiles[0].configure(text=f"{amt:f}")
    v=d.pos_vals
    if not amt:
        d.pos_side.configure(text="포지션 없음",bg=CHIP,fg=INK)
        d.pos_pnl.configure(text="—",fg=INK)
        for w in v.values():
            w.configure(text="—",fg=INK)
        return
    entry=D(pos["entryPrice"]); mark=D(pos["markPrice"]); upnl=D(pos["unRealizedProfit"])
    liq=D(pos["liquidationPrice"]); notional=abs(D(pos["notional"]))
    margin=abs(amt)*entry/lev
    roe=100*upnl/margin if margin else D(0)
    ratio=100*maint/equity if equity else D(0)
    long=amt>0
    d.pos_side.configure(text="Long" if long else "Short",bg=UP if long else DOWN,fg=BG)
    d.pos_pnl.configure(text=f"{upnl:+,.2f} ({roe:+.2f}%)",fg=tone(upnl))
    v["size"].configure(text=f"{notional:,.2f}")
    v["margin"].configure(text=f"{margin:,.2f}")
    v["ratio"].configure(text=f"{ratio:.2f}%",fg=DOWN if ratio>=50 else INK)
    v["entry"].configure(text=f"{entry:,.1f}")
    v["mark"].configure(text=f"{mark:,.1f}")
    v["liq"].configure(text=f"{liq:,.1f}" if liq else "—",fg=GOLD)


def show_price(d,last,chg,mark):
    tone=UP if chg>0 else DOWN if chg<0 else INK
    d.price_lbl.configure(text=f"{last:,.1f}",fg=tone)
    d.chg_lbl.configure(text=f"{chg:+.2f}%   ·   Mark {mark:,.1f}",fg=tone)


HELP_STEPS = [
    ("demo.binance.com", " 에 접속해 바이낸스 계정으로 로그인 (위에 DEMO TRADING 표시)"),
    ("오른쪽 위 사람 아이콘", " → Demo Trading API"),
    ("Create API", " (노란 버튼) 클릭"),
    ("System generated", " 선택 → Next"),
    ("이름 입력", " (예: KBTC) → Next"),
    ("API Key 옆 Copy", " → KBTC 의 API Key 칸에 붙여넣기"),
    ("Secret Key 옆 Copy", " → KBTC 의 Secret Key 칸에 붙여넣기\n   (Secret 은 이 화면을 벗어나면 다시 볼 수 없어요. 놓치면 Delete 후 새로 만들기)"),
    ("API restrictions", " 에서 Enable Futures 체크 확인"),
    ("KBTC 에서 계좌 환경 Demo", " → 계좌 연결 · 조회 → 퀀트 트레이딩 시작"),
]


def api_help(root):
    """바이낸스 Demo API 키 만드는 법 안내 창."""
    import webbrowser
    w = tk.Toplevel(root)
    w.title("API 키 만드는 법")
    w.configure(bg=PANEL)
    w.resizable(False, False)
    tk.Label(w, text="바이낸스 Demo API 키 만드는 법", bg=PANEL, fg=INK, font=("Malgun Gothic", 15, "bold"),
             anchor="w").pack(fill="x", padx=18, pady=(16, 8))
    for i, (strong, rest) in enumerate(HELP_STEPS, 1):
        row = tk.Frame(w, bg=PANEL)
        row.pack(fill="x", padx=18, pady=3)
        tk.Label(row, text=f" {i} ", bg="#2a2c31", fg=GOLD, font=("Malgun Gothic", 10, "bold")).pack(side="left", anchor="n")
        t = tk.Text(row, bg=PANEL, fg=INK, relief="flat", height=rest.count("\n") + 1, width=62, wrap="word",
                    font=("Malgun Gothic", 11), highlightthickness=0, bd=0)
        t.tag_configure("b", foreground=GOLD, font=("Malgun Gothic", 11, "bold"))
        t.insert("end", strong, "b"); t.insert("end", rest)
        t.configure(state="disabled")
        t.pack(side="left", padx=(8, 0))
    tk.Label(w, text="• Demo 키는 모의 계좌라 진짜 돈이 움직이지 않아요.\n"
                     "• 선물 포지션 모드는 기본값인 단방향(One-way) 이어야 해요.\n"
                     "• Live(실계좌)는 binance.com API 관리에서 Futures 만 켜고 출금 권한은 끄세요.\n"
                     "• API Key·Secret 은 비밀번호처럼 다른 사람에게 보내지 마세요.",
             bg="#1e2026", fg=MUTED, justify="left", anchor="w", font=("Malgun Gothic", 10), padx=12, pady=10
             ).pack(fill="x", padx=18, pady=(10, 6))
    Pill(w, "바이낸스 Demo API 관리 열기 ↗",
         lambda: webbrowser.open("https://demo.binance.com/en/my/settings/api-management"),
         "#2a2c31", "#3a3d44", fg=GOLD).pack(fill="x", padx=18, pady=(6, 16))


VERDICT_COLOR = {"보수": MUTED, "안정": MINT, "균형": UP, "공격": "#a3d977", "공격 · 추천 상한": GOLD, "위험": "#ff9f43", "매우 위험": DOWN}


def backtest_window(root, d=None):
    """BTC · 비중 30% · 배율별 백테스트 결과를 한눈에."""
    import json, os
    base = os.path.join(os.path.dirname(__file__), "assets")
    data = json.load(open(os.path.join(base, "backtest_btc_w30.json"), encoding="utf-8"))
    w = tk.Toplevel(root)
    w.title("배율별 백테스트 · BTC · 비중 30%")
    w.configure(bg=BG)
    w.resizable(False, False)
    tk.Label(w, text="배율별 백테스트  ·  BTC  ·  비중 30%", bg=BG, fg=INK, font=("Malgun Gothic", 16, "bold"),
             anchor="w").pack(fill="x", padx=18, pady=(14, 0))
    tk.Label(w, text=f"Lv.1 50일선 추세 · {data['start']} ~ {data['end']} · 시작 {data['capital']:,} USDT · "
                     f"수수료·슬리피지·실제 펀딩비·마크가격 청산 반영 · 복리",
             bg=BG, fg=MUTED, font=("Malgun Gothic", 10), anchor="w").pack(fill="x", padx=18, pady=(2, 8))
    body = tk.Frame(w, bg=BG)
    body.pack(fill="both", padx=18)
    leftc = tk.Frame(body, bg=BG)
    leftc.pack(side="left", fill="y", anchor="n")
    tab = tk.Frame(leftc, bg=PANEL, padx=10, pady=8)
    tab.pack(fill="x")
    heads = ["배율", "실노출", "최종 계좌 잔액", "연평균", "최대 낙폭", "낙폭 때 계좌 (고점 → 바닥)", "최악의 해", "판정"]
    for c, h in enumerate(heads):
        tab.columnconfigure(c, weight=1)
        tk.Label(tab, text=h, bg=PANEL, fg=MUTED, font=("Malgun Gothic", 10, "bold")).grid(row=0, column=c, sticky="ew", pady=(0, 6))
    try:
        cur = int(d.lev_entry.get()) if d else None
    except ValueError:
        cur = None
    tone = lambda v: UP if v > 0 else DOWN if v < 0 else INK
    pc = lambda v, sign="": f"{v * 100:{sign}.2f}%" if v <= -0.99 else f"{v * 100:{sign}.1f}%"
    for i, r in enumerate(data["rows"], 1):
        trough = r["peak_usdt"] * (1 + r["mdd"])
        bg = "#23262d" if r["lev"] == cur else PANEL
        vals = [(f"{r['lev']}배" + ("  ◀ 지금" if r["lev"] == cur else ""), INK), (f"{r['expo']:.1f}배", MUTED),
                (f"{r['usdt']:,.0f}", tone(r["final"] - 1)), (pc(r["cagr"], "+"), tone(r["cagr"])),
                (pc(r["mdd"]), DOWN if r["mdd"] < -0.6 else INK),
                (f"{r['peak_usdt']:,.0f} → {trough:,.0f}", DOWN if r["mdd"] < -0.9 else MUTED),
                (pc(r["worst_year"], "+"), tone(r["worst_year"]))]
        for c, (v, col) in enumerate(vals):
            tk.Label(tab, text=v, bg=bg, fg=col, font=("Malgun Gothic", 11, "bold"), padx=4).grid(row=i, column=c, sticky="ew", ipady=2)
        tk.Label(tab, text=r["verdict"], bg=VERDICT_COLOR.get(r["verdict"], MUTED), fg=BG,
                 font=("Malgun Gothic", 10, "bold"), padx=6).grid(row=i, column=7, padx=4, pady=2)
    tk.Label(leftc, text=f"모든 금액·%는 전체 계좌 잔액(USDT) 기준이에요. 시작 {data['capital']:,} USDT.   "
                         f"BTC 그냥 보유: {data['hold']:.1f}배 (최대 낙폭 {data['hold_mdd'] * 100:.1f}%)", bg=BG, fg=MUTED,
             font=("Malgun Gothic", 10), anchor="w").pack(fill="x", pady=(6, 6))
    if data.get("curves"):
        BacktestChart(body, data, cur).pack(side="left", padx=(14, 0), anchor="n")
    tk.Label(leftc, text="• 실노출 = 배율 × 비중. 교차(Cross) 계좌에선 이 값이 수익과 위험을 정해요.\n"
                     "• 최대 낙폭 = 계좌 잔액이 가장 높았던 때 대비 가장 많이 줄었던 비율. 최악의 해 = 그해 계좌 잔액 증감.\n"
                     "• 9배에서 최종 잔액이 가장 크지만 낙폭 -92.5%. 10배부턴 수익도 줄고, 20배는 65만 → 183 USDT까지 떨어졌어요.\n"
                     "• 추천: 비중 30%면 배율 3~5배 (실노출 0.9~1.5배). 과거 결과일 뿐 미래 수익을 보장하지 않아요.",
             bg="#16181d", fg=INK, justify="left", anchor="w", font=("Malgun Gothic", 10), padx=12, pady=10
             ).pack(fill="x", pady=(0, 16))


LEV_COLOR = {"1": "#9ea2aa", "2": "#88e6c4", "3": "#3ecf7a", "4": "#a3d977", "5": "#ffc56b", "6": "#ffb05c", "7": "#ffa14f",
             "8": "#ff9343", "9": "#ff8a3d", "10": "#ff7a45", "15": "#ff5f7e", "20": "#c0392b"}


class BacktestChart(tk.Canvas):
    """배율별 자산 곡선 (로그 축). 이미지가 아니라 선으로 그려 레티나에서도 선명. 범례 클릭 = 강조."""
    W, H = 560, 470

    def __init__(self, parent, data, cur=None):
        super().__init__(parent, bg=CARD, width=self.W, height=self.H, highlightthickness=0)
        self.data, self.focus = data, (str(cur) if cur else None)
        self.draw()

    def draw(self):
        import math
        from datetime import date
        self.delete("all")
        cv = self.data["curves"]
        L, R, T, B = 58, self.W - 14, 66, self.H - 34
        keys = [k for k in cv if k != "hold"]
        vals = [v for k in cv for _, v in cv[k] if v > 0]
        lo, hi = max(min(vals), 0.05), max(vals)
        ly0, ly1 = math.log10(lo), math.log10(hi) + 0.05
        d0 = date.fromisoformat(cv["hold"][0][0]).toordinal(); d1 = date.fromisoformat(cv["hold"][-1][0]).toordinal()
        X = lambda ds: L + (date.fromisoformat(ds).toordinal() - d0) / (d1 - d0) * (R - L)
        Y = lambda v: B - (math.log10(max(v, lo)) - ly0) / (ly1 - ly0) * (B - T)
        f = ("Malgun Gothic", 10)
        self.create_text(L, 14, text="배율별 자산 (시작 = 1배, 로그 축)", anchor="w", fill=INK, font=("Malgun Gothic", 11, "bold"))
        for e in range(math.floor(ly0), math.ceil(ly1) + 1):
            for m in (1, 3):
                v = m * 10 ** e
                if lo <= v <= 10 ** ly1:
                    y = Y(v)
                    self.create_line(L, y, R, y, fill="#24272e" if m == 3 else "#33363d")
                    self.create_text(L - 6, y, text=f"{v:g}배", anchor="e", fill=MUTED, font=f)
        for yr in range(int(cv["hold"][0][0][:4]), int(cv["hold"][-1][0][:4]) + 1):
            x = X(f"{yr}-01-01") if yr > int(cv["hold"][0][0][:4]) else L
            if L <= x <= R:
                self.create_line(x, T, x, B, fill="#24272e")
                self.create_text(x, B + 14, text=str(yr), fill=MUTED, font=f)
        def line(k, color, width, dash=None):
            pts = []
            for ds, v in cv[k]:
                if v <= 0:
                    break
                pts += [X(ds), Y(v)]
            if len(pts) >= 4:
                self.create_line(*pts, fill=color, width=width, dash=dash, smooth=False)
        line("hold", INK, 1, dash=(3, 3))
        order = sorted(keys, key=lambda k: k == self.focus)
        for k in order:
            dim = self.focus and k != self.focus
            line(k, "#3a3d44" if dim else LEV_COLOR.get(k, INK), 3 if k == self.focus else 1.6)
        # 범례 (클릭하면 그 배율 강조)
        x, ly = L + 4, 34
        for k in keys + ["hold"]:
            if x > R - 50:
                x, ly = L + 4, ly + 18
            name = "보유" if k == "hold" else f"{k}배"
            col = INK if k == "hold" else LEV_COLOR.get(k, INK)
            tag = f"lg{k}"
            self.create_rectangle(x, ly - 2, x + 12, ly + 2, fill=col, outline="", tags=tag)
            t = self.create_text(x + 16, ly, text=name, anchor="w", font=("Malgun Gothic", 10, "bold"),
                                 fill=col if (not self.focus or k == self.focus or k == "hold") else MUTED, tags=tag)
            x = self.bbox(t)[2] + 12
            if k != "hold":
                self.tag_bind(tag, "<Button-1>", lambda e, k=k: self.toggle(k))
                self.tag_bind(tag, "<Enter>", lambda e: self.configure(cursor="hand2"))
                self.tag_bind(tag, "<Leave>", lambda e: self.configure(cursor=""))

    def toggle(self, k):
        self.focus = None if self.focus == k else k
        self.draw()
