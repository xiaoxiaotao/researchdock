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
 private final Context context; private final int size; private final Images images;
 private static final int INK=Color.rgb(38,48,47),GREEN=Color.rgb(31,105,82),BLUE=Color.rgb(49,91,132),AMBER=Color.rgb(145,91,29);
 ResearchText(Context context,int size,Images images){this.context=context;this.size=size;this.images=images;}
 private int dp(int n){return Math.round(n*context.getResources().getDisplayMetrics().density);}
 private GradientDrawable background(int color,int border){GradientDrawable g=new GradientDrawable();g.setColor(color);g.setCornerRadius(dp(10));if(border!=0)g.setStroke(dp(1),border);return g;}
 private TextView label(CharSequence value,int font,int color){TextView v=new TextView(context);v.setText(value);v.setTextSize(font);v.setTextColor(color);v.setLinkTextColor(BLUE);v.setTextIsSelectable(true);v.setLineSpacing(dp(5),1.12f);v.setPadding(0,dp(7),0,dp(7));if(value instanceof Spanned && ((Spanned)value).getSpans(0,value.length(),URLSpan.class).length>0)v.setMovementMethod(LinkMovementMethod.getInstance());return v;}
 private void span(SpannableStringBuilder b,Object span,int start){if(b.length()>start)b.setSpan(span,start,b.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);}
 CharSequence inline(String source){
  SpannableStringBuilder out=new SpannableStringBuilder();
  Matcher m=Pattern.compile("\\*\\*(.+?)\\*\\*|__(.+?)__|`([^`]+)`|\\[([^]\\n]+)\\]\\((https?://[^\\s)]+)\\)|(https?://[^\\s<>]+)").matcher(source);int end=0;
  while(m.find()){out.append(source.substring(end,m.start()));int at=out.length();
   if(m.group(1)!=null||m.group(2)!=null){out.append(m.group(1)!=null?m.group(1):m.group(2));span(out,new StyleSpan(Typeface.BOLD),at);}
   else if(m.group(3)!=null){out.append(m.group(3));span(out,new TypefaceSpan("monospace"),at);span(out,new BackgroundColorSpan(Color.rgb(232,237,236)),at);}
   else{String url=m.group(5)!=null?m.group(5):m.group(6);out.append(m.group(4)!=null?m.group(4):url);span(out,new URLSpan(url),at);}
   end=m.end();
  }out.append(source.substring(end));
  // Colour metric names only. Do not label numbers as good/bad or generate new claims.
  Matcher metrics=Pattern.compile("营业收入|营收|净利润|毛利率|净利率|经营现金流|自由现金流|现金流|每股收益|ROE|EBITDA").matcher(out);
  while(metrics.find()){out.setSpan(new ForegroundColorSpan(BLUE),metrics.start(),metrics.end(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);out.setSpan(new StyleSpan(Typeface.BOLD),metrics.start(),metrics.end(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);}
  return out;
 }
 private void paragraph(LinearLayout parent,String text){if(!text.isEmpty())parent.addView(label(inline(text),size,INK));}
 private boolean divider(String line){return line.matches("\\s*\\|?\\s*:?-{3,}:?\\s*(\\|\\s*:?-{3,}:?\\s*)+\\|?\\s*");}
 private String[] cells(String line){String value=line.trim();if(value.startsWith("|"))value=value.substring(1);if(value.endsWith("|"))value=value.substring(0,value.length()-1);return value.split("(?<!\\\\)\\|",-1);}
 private void table(LinearLayout parent,List<String> rows){HorizontalScrollView scroll=new HorizontalScrollView(context);TableLayout table=new TableLayout(context);scroll.addView(table);int cols=cells(rows.get(0)).length;
  for(int r=0;r<rows.size();r++){TableRow row=new TableRow(context);String[] values=cells(rows.get(r));for(int c=0;c<Math.max(cols,values.length);c++){TextView v=label(inline(c<values.length?values[c].trim().replace("\\|","|"):""),size-2,r==0?GREEN:INK);v.setMinWidth(dp(120));v.setMaxWidth(dp(260));v.setPadding(dp(12),dp(10),dp(12),dp(10));v.setBackground(background(r==0?Color.rgb(225,237,230):r%2==0?Color.rgb(245,247,245):Color.WHITE,Color.rgb(220,228,222)));if(r==0)v.setTypeface(Typeface.DEFAULT,Typeface.BOLD);row.addView(v);}table.addView(row);}parent.addView(scroll,new LinearLayout.LayoutParams(-1,-2));parent.addView(label("表格可左右滑动",11,Color.GRAY));
 }
 void render(LinearLayout parent,String source){String[] lines=source.replace("\r","").split("\n",-1);StringBuilder pending=new StringBuilder();LinearLayout section=parent;boolean code=false;
  for(int i=0;i<=lines.length;i++){String line=i<lines.length?lines[i]:"",trim=line.trim();
   boolean heading=trim.matches("[^：:|]{2,20}[：:]")||trim.matches("#{1,6}\\s+.+")||trim.matches("【[^】]{1,40}】")||trim.matches("[一二三四五六七八九十]+[、．].{1,40}");
   boolean bullet=trim.matches("(?:[-*+]\\s+|[0-9]+[.)、]\\s*).+"),quote=trim.startsWith(">"),rule=trim.matches("(?:-{3,}|\\*{3,}|_{3,})");
   boolean tabular=i+1<lines.length&&trim.contains("|")&&divider(lines[i+1]);
   Matcher image=Pattern.compile("!\\[([^]]*)\\]\\((asset:[a-f0-9]{64}|https?://[^\\s)]+)\\)").matcher(trim);boolean img=image.matches();
   boolean callout=trim.matches("(?:\\*\\*)?(?:核心观点|核心结论|投资要点|研究要点|风险提示|风险因素)(?:\\*\\*)?[：:].*");
   if(trim.isEmpty()||heading||bullet||quote||rule||tabular||img||callout||trim.startsWith("```")){
    if(pending.length()>0){paragraph(section,pending.toString());pending.setLength(0);}
    if(trim.startsWith("```")){code=!code;continue;}if(trim.isEmpty())continue;
    if(tabular){List<String> rows=new ArrayList<>();rows.add(line);i+=2;while(i<lines.length&&lines[i].contains("|")&&!lines[i].trim().isEmpty()){rows.add(lines[i]);i++;}i--;table(section,rows);continue;}
    if(rule){View v=new View(context);v.setBackgroundColor(Color.rgb(214,224,217));LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,dp(1));lp.setMargins(0,dp(16),0,dp(16));section.addView(v,lp);continue;}
    if(img){String uri=image.group(2);if(uri.startsWith("asset:"))images.add(section,uri.substring(6),image.group(1));else{section.addView(label("图片尚未归档至私有服务",12,Color.GRAY));section.addView(label(inline("[查看原图链接]("+uri+")"),size-2,BLUE));}continue;}
    if(heading||callout){String value=trim.replaceFirst("^#{1,6}\\s+","").replace("**","");boolean risk=value.matches("[【\\s]*(风险提示|风险因素).*"),key=value.matches("[【\\s]*(核心观点|核心结论|投资要点|研究要点).*" );int level=trim.startsWith("#")?trim.indexOf(' '):2;
     section=parent;if(risk||key){section=new LinearLayout(context);section.setOrientation(LinearLayout.VERTICAL);section.setPadding(dp(14),dp(8),dp(14),dp(12));section.setBackground(background(risk?Color.rgb(251,243,228):Color.rgb(232,241,235),risk?Color.rgb(224,194,144):Color.rgb(182,211,192)));LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.setMargins(0,dp(14),0,dp(12));parent.addView(section,lp);}
     TextView v=label(inline(value),size+(level==1?7:level==2?4:2),risk?AMBER:level<=2?GREEN:BLUE);v.setTypeface(Typeface.DEFAULT,Typeface.BOLD);v.setPadding(0,dp(16),0,dp(8));section.addView(v);continue;}
    TextView v=label(inline(quote?trim.replaceFirst("^>\\s?",""):trim.replaceFirst("^[-*+]\\s+","• ")),size,quote?Color.rgb(95,111,104):INK);if(quote){v.setPadding(dp(14),dp(10),dp(14),dp(10));v.setBackground(background(Color.rgb(236,240,237),Color.rgb(209,220,212)));}else v.setPadding(dp(10),dp(5),0,dp(5));section.addView(v);
   }else if(code){TextView v=label(line,size-2,INK);v.setTypeface(Typeface.MONOSPACE);section.addView(v);}else{if(pending.length()>0)pending.append("\n");pending.append(line);}
  }
 }
}
