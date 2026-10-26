package org.researchdock.mobile;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.regex.*;
/** Searches only current-revision cached bodies still present in the authoritative catalog. */
final class LocalSearch {
 static JSONObject read(File file)throws Exception{try(InputStream in=new FileInputStream(file)){ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){if(out.size()+n>2_000_000)throw new IOException("缓存过大");out.write(b,0,n);}return new JSONObject(out.toString("UTF-8"));}}
 static boolean scope(JSONObject d,String company,String industry,String source,int days){
  if(!source.isEmpty()&&!source.equals(d.optString("source_name")))return false;
  if(days>0)try{LocalDate stamp;try{stamp=OffsetDateTime.parse(d.optString("published_at")).atZoneSameInstant(ZoneId.of("Asia/Shanghai")).toLocalDate();}catch(Exception e){stamp=LocalDate.parse(LibraryViews.day(d));}LocalDate now=LocalDate.now(ZoneId.of("Asia/Shanghai"));if(stamp.isBefore(now.minusDays(days-1))||stamp.isAfter(now))return false;}catch(Exception e){return false;}
  if(!industry.isEmpty()&&!contains(d.optJSONArray("industries"),industry))return false;
  if(!company.isEmpty()&&!contains(d.optJSONArray("companies"),company)){boolean found=false;JSONArray refs=d.optJSONArray("company_securities");if(refs!=null)for(int n=0;n<refs.length();n++){JSONObject r=refs.optJSONObject(n);if(r!=null&&(company.equals(r.optString("canonical_name"))||company.equals(r.optString("name"))))found=true;}if(!found)return false;}return true;
 }
 private static boolean contains(JSONArray a,String q){if(a!=null)for(int i=0;i<a.length();i++)if(q.equals(a.optString(i)))return true;return false;}
 static JSONObject hit(JSONObject d,String q)throws JSONException{
  Pattern p=Pattern.compile(Pattern.quote(q),Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE);String body=d.optString("body");Matcher m=p.matcher(body);String field="body";
  if(!m.find()){body=d.optString("title");m=p.matcher(body);field="title";if(!m.find()){StringBuilder names=new StringBuilder();JSONArray attachments=d.optJSONArray("attachments");if(attachments!=null)for(int k=0;k<attachments.length();k++){JSONObject a=attachments.optJSONObject(k);if(a!=null)names.append(a.optString("name")).append(" ");}String metadata=d.optString("companies")+d.optString("company_securities")+d.optString("industries")+names;if(!p.matcher(metadata).find())return null;body="命中公司、代码、行业或附件名称";field="metadata";m=null;}}
  int start=m==null?0:Math.max(0,m.start()-65);JSONObject compact=new JSONObject();for(String key:new String[]{"document_id","revision","title","source_name","published_at","content_kind"})compact.put(key,d.opt(key));
  return new JSONObject().put("document",compact).put("snippet",body.substring(start,Math.min(body.length(),start+210))).put("match_field",field).put("offset",start).put("match_start",m==null?-1:m.start()-start).put("match_end",m==null?-1:m.end()-start);
 }
 static JSONObject search(File directory,JSONArray catalog,String q,String company,String industry,String source,int days)throws Exception{
  JSONArray results=new JSONArray();int checked=0,stale=0;boolean more=false;
  for(int n=0;n<catalog.length();n++){JSONObject meta=catalog.optJSONObject(n);if(meta==null||!scope(meta,company,industry,source,days))continue;String id=meta.optString("document_id");if(!id.matches("doc_[0-9A-Z]{26}"))continue;JSONObject body=null;String filename="";
   for(String candidate:new String[]{id+".json","research-source-"+id+".json"})try{File file=new File(directory,candidate);if(!file.isFile())continue;JSONObject cached=read(file);if(!id.equals(cached.optString("document_id"))||cached.optInt("revision")!=meta.optInt("revision")){stale++;continue;}if(!cached.has("body"))continue;body=OriginalFiles.mergeCached(cached,meta);filename=candidate;break;}catch(Exception ignored){}
   if(body==null)continue;checked++;JSONObject match=hit(body,q);if(match==null)continue;if(results.length()==40){more=true;break;}match.put("cache",filename);results.put(match);
  }
  return new JSONObject().put("scope","local_current_cached_text").put("results",results).put("has_more",more).put("scanned_cached_documents",checked).put("excluded_stale_caches",stale).put("model_requests",0);
 }
}
