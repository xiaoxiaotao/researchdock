package org.researchdock.mobile;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.*;
import android.text.style.*;
import android.text.method.LinkMovementMethod;
import android.view.View;
import android.widget.*;
import java.util.*;
import java.util.regex.*;

/** Local, non-executable reading presentation. Never infers investment conclusions. */
final class ResearchText {
 interface Images { void add(LinearLayout parent,String id,String caption); }
 private final Context context; private final int size; private final Images images; private List<TextView> headings;
 private static final int INK=Color.rgb(48,38,39),ACCENT=ReaderTheme.ACCENT,BLUE=Color.rgb(49,91,132),AMBER=Color.rgb(145,91,29);
 private static final Pattern P0=Pattern.compile("\\*\\*(.+?)\\*\\*|__(.+?)__|`([^`]+)`|\\[([^]\\n]+)\\]\\((https?://[^\\s)]+)\\)|(https?://[^\\s<>]+)");
 private static final Pattern P1=Pattern.compile("营业收入|营收|净利润|毛利率|净利率|经营现金流|自由现金流|现金流|每股收益|ROE|EBITDA");
 private static final Pattern P2=Pattern.compile("(?<![A-Za-z0-9])[-+−]?\\d+(?:[.,]\\d+)*(?:%|％|亿元|万元|亿|万|元|个百分点|倍)");
 private static final Pattern P3=Pattern.compile("!\\[([^]]*)\\]\\((asset:[a-f0-9]{64}|https?://[^\\s)]+)\\)");
 private static final Pattern P4=Pattern.compile("\\s*\\|?\\s*:?-{3,}:?\\s*(\\|\\s*:?-{3,}:?\\s*)+\\|?\\s*");
 private static final Pattern P5=Pattern.compile("[^：:|]{2,20}[：:]");
 private static final Pattern P6=Pattern.compile("#{1,6}\\s+.+");
 private static final Pattern P7=Pattern.compile("【[^】]{1,40}】");
 private static final Pattern P8=Pattern.compile("[一二三四五六七八九十]+[、．].{1,40}");
 private static final Pattern P9=Pattern.compile("(?:[-*+]\\s+|[0-9]+[.)、]\\s*).+");
 private static final Pattern P10=Pattern.compile("(?:-{3,}|\\*{3,}|_{3,})");
 private static final Pattern P11=Pattern.compile("(?:\\*\\*)?(?:核心观点|核心结论|投资要点|研究要点|风险提示|风险因素)(?:\\*\\*)?[：:].*");
 private static final Pattern P12=Pattern.compile("[【\\s]*(风险提示|风险因素).*");
 ResearchText(Context context,int size,Images images){this.context=context;this.size=size;this.images=images;}
 ResearchText(Context context,int size,List<TextView> headings,Images images){this(context,size,images);this.headings=headings;}
 private int dp(int n){return Math.round(n*context.getResources().getDisplayMetrics().density);}
 private GradientDrawable background(int color,int border){GradientDrawable g=new GradientDrawable();g.setColor(color);g.setCornerRadius(dp(10));if(border!=0)g.setStroke(dp(1),border);return g;}
 @android.annotation.SuppressLint("WrongConstant") // Layout constants remain available on Android 8; LineBreaker starts at API 29.
 private TextView label(CharSequence value,int font,int color){TextView v=new TextView(context);v.setText(value);v.setTextSize(font);v.setTextColor(color);v.setLinkTextColor(BLUE);v.setBreakStrategy(android.text.Layout.BREAK_STRATEGY_SIMPLE);v.setHyphenationFrequency(android.text.Layout.HYPHENATION_FREQUENCY_NONE);v.setTextIsSelectable(true);v.setLineSpacing(dp(5),1.12f);v.setPadding(0,dp(7),0,dp(7));if(value instanceof Spanned && ((Spanned)value).getSpans(0,value.length(),URLSpan.class).length>0)v.setMovementMethod(LinkMovementMethod.getInstance());return v;}
 private void span(SpannableStringBuilder b,Object span,int start){if(b.length()>start)b.setSpan(span,start,b.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);}
 CharSequence inline(String source){
  SpannableStringBuilder out=new SpannableStringBuilder();
  Matcher m=P0.matcher(source);int end=0;
  while(m.find()){out.append(source.substring(end,m.start()));int at=out.length();
   if(m.group(1)!=null||m.group(2)!=null){out.append(m.group(1)!=null?m.group(1):m.group(2));span(out,new StyleSpan(Typeface.BOLD),at);}
   else if(m.group(3)!=null){out.append(m.group(3));span(out,new TypefaceSpan("monospace"),at);span(out,new BackgroundColorSpan(Color.rgb(238,235,234)),at);}
   else{String url=m.group(5)!=null?m.group(5):m.group(6);String caption=m.group(4);if(caption==null){try{caption="↗ 来源链接 · "+new java.net.URI(url).getHost();}catch(Exception e){caption="↗ 原文链接";}}out.append(caption);span(out,new URLSpan(url),at);}
   end=m.end();
  }out.append(source.substring(end));
  // Colour metric names only. Do not label numbers as good/bad or generate new claims.
  Matcher metrics=P1.matcher(out);
  while(metrics.find()){out.setSpan(new ForegroundColorSpan(BLUE),metrics.start(),metrics.end(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);out.setSpan(new StyleSpan(Typeface.BOLD),metrics.start(),metrics.end(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);}
  Matcher amounts=P2.matcher(out);while(amounts.find())out.setSpan(new ForegroundColorSpan(BLUE),amounts.start(),amounts.end(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
  return out;
 }
 private void paragraph(LinearLayout parent,String text){if(!text.isEmpty())parent.addView(label(inline(text),size,INK));}
 private boolean divider(String line){return P4.matcher(line).matches();}
 private String[] cells(String line){String value=line.trim();if(value.startsWith("|"))value=value.substring(1);if(value.endsWith("|"))value=value.substring(0,value.length()-1);return value.split("(?<!\\\\)\\|",-1);}
 private void table(LinearLayout parent,List<String> rows){HorizontalScrollView scroll=new HorizontalScrollView(context);TableLayout table=new TableLayout(context);scroll.addView(table);int cols=cells(rows.get(0)).length;
  for(int r=0;r<rows.size();r++){TableRow row=new TableRow(context);String[] values=cells(rows.get(r));for(int c=0;c<Math.max(cols,values.length);c++){TextView v=label(inline(c<values.length?values[c].trim().replace("\\|","|"):""),size-2,r==0?ACCENT:INK);v.setMinWidth(dp(120));v.setMaxWidth(dp(260));v.setPadding(dp(12),dp(10),dp(12),dp(10));v.setBackground(background(r==0?ReaderTheme.SOFT:r%2==0?Color.rgb(248,245,244):Color.WHITE,Color.rgb(226,223,222)));if(r==0)v.setTypeface(Typeface.DEFAULT,Typeface.BOLD);row.addView(v);}table.addView(row);}parent.addView(scroll,new LinearLayout.LayoutParams(-1,-2));parent.addView(label("表格可左右滑动",11,Color.GRAY));
 }
 void render(LinearLayout parent,String source){new Session(parent,source).pump(Integer.MAX_VALUE);}
 void renderAsync(LinearLayout parent,String source,java.util.function.BooleanSupplier active,Runnable done){Session session=new Session(parent,source);Runnable batch=new Runnable(){public void run(){if(!active.getAsBoolean())return;if(session.pump(12))done.run();else parent.postOnAnimation(this);}};batch.run();}
 private final class Session {
  final String[] lines;final StringBuilder pending=new StringBuilder();final LinearLayout parent;LinearLayout section;boolean code=false;int i=0;
  Session(LinearLayout parent,String source){this.parent=parent;this.section=parent;this.lines=source.replace("\r","").split("\n",-1);}
  boolean pump(int quota){long until=System.nanoTime()+6000000L;int processed=0;
  for(;i<=lines.length;i++){if(quota!=Integer.MAX_VALUE&&(processed>=quota||(processed>0&&System.nanoTime()>until)))return false;processed++;String line=i<lines.length?lines[i]:"",trim=line.trim();
   boolean heading=P5.matcher(trim).matches()||P6.matcher(trim).matches()||P7.matcher(trim).matches()||P8.matcher(trim).matches();
   boolean bullet=P9.matcher(trim).matches(),quote=trim.startsWith(">"),rule=P10.matcher(trim).matches();
   boolean tabular=i+1<lines.length&&trim.contains("|")&&divider(lines[i+1]);
   Matcher image=P3.matcher(trim);boolean img=image.matches();
   boolean callout=P11.matcher(trim).matches();
   if(trim.isEmpty()||heading||bullet||quote||rule||tabular||img||callout||trim.startsWith("```")){
    if(pending.length()>0){paragraph(section,pending.toString());pending.setLength(0);}
    if(trim.startsWith("```")){code=!code;continue;}if(trim.isEmpty())continue;
    if(tabular){List<String> rows=new ArrayList<>();rows.add(line);i+=2;while(i<lines.length&&lines[i].contains("|")&&!lines[i].trim().isEmpty()){rows.add(lines[i]);i++;}i--;table(section,rows);continue;}
    if(rule){View v=new View(context);v.setBackgroundColor(Color.rgb(221,218,217));LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,dp(1));lp.setMargins(0,dp(16),0,dp(16));section.addView(v,lp);continue;}
    if(img){String uri=image.group(2);if(uri.startsWith("asset:"))images.add(section,uri.substring(6),image.group(1));else{section.addView(label("图片尚未归档至私有服务",12,Color.GRAY));section.addView(label(inline("[查看原图链接]("+uri+")"),size-2,BLUE));}continue;}
    if(heading||callout){String value=trim.replaceFirst("^#{1,6}\\s+","").replace("**","");boolean risk=P12.matcher(value).matches(),key=value.matches("[【\\s]*(核心观点|核心结论|投资要点|研究要点).*" );int level=trim.startsWith("#")?trim.indexOf(' '):2;
     section=parent;if(risk||key){section=new LinearLayout(context);section.setOrientation(LinearLayout.VERTICAL);section.setPadding(dp(14),dp(8),dp(14),dp(12));section.setBackground(background(risk?Color.rgb(251,243,228):ReaderTheme.SOFT,risk?Color.rgb(224,194,144):Color.rgb(211,182,185)));LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.setMargins(0,dp(14),0,dp(12));parent.addView(section,lp);}
     TextView v=label(inline(value),size+(level==1?7:level==2?4:2),risk?AMBER:level<=2?ACCENT:BLUE);v.setTypeface(Typeface.DEFAULT,Typeface.BOLD);v.setPadding(0,dp(16),0,dp(8));section.addView(v);if(headings!=null)headings.add(v);continue;}
    TextView v=label(inline(quote?trim.replaceFirst("^>\\s?",""):trim.replaceFirst("^[-*+]\\s+","• ")),size,quote?Color.rgb(111,95,96):INK);if(quote){v.setPadding(dp(14),dp(10),dp(14),dp(10));v.setBackground(background(Color.rgb(240,237,236),Color.rgb(216,213,212)));}else v.setPadding(dp(10),dp(5),0,dp(5));section.addView(v);
   }else if(code){TextView v=label(line,size-2,INK);v.setTypeface(Typeface.MONOSPACE);section.addView(v);}else{if(pending.length()>0)pending.append("\n");pending.append(line);if(pending.length()>1800){paragraph(section,pending.toString());pending.setLength(0);}}
  }return true;
  }
 }
}
